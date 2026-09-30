#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Describe native series and check DCP metadata coverage; never score a new
loss band.

Only use --campaign with this campaign's trusted retained checkpoints. Reading
DCP .metadata uses pickle (code-execution capable), not torch.load or tensor
payloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import pickle
from pathlib import Path
from typing import Any

from c2_parameter_verdict_927c5de import canonical_sha256
from extract_c2_native import parse_arm


ARM_ORDER = ("P-M1-off", "P-M1-on", "P-M2-on", "P-M2-off")
PRODUCT_SHA = "927c5de2f5a8f307cad0c87f2c7eb2b78262334d"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def coverage(metadata: Any, inventory: dict[str, Any], adapter: dict[str, Any]) -> dict[str, Any]:
    """Match tensor metadata bijectively and verify chunk bounds/non-
    overlap/volume."""
    rows = inventory["tensors"]
    names = [row["name"].split("::", 1)[1] for row in rows]
    if len(names) != len(set(names)):
        raise ValueError("duplicate inventory tensor name")
    by_name = dict(zip(names, rows, strict=True))
    tensors = {}
    bytes_keys = []
    for key, item in metadata.state_dict_metadata.items():
        if not hasattr(item, "size"):
            bytes_keys.append(key)
            continue
        shape = list(item.size)
        dtype = str(item.properties.dtype).removeprefix("torch.")
        row = by_name.get(key)
        if row is None or row["shape"] != shape or row["dtype"] != dtype:
            raise ValueError(f"DCP tensor missing/shape/dtype mismatch: {key}")
        total = math.prod(shape)
        boxes = []
        volume = 0
        for chunk in item.chunks:
            offsets, sizes = list(chunk.offsets), list(chunk.sizes)
            if len(offsets) != len(shape) or len(sizes) != len(shape):
                raise ValueError(f"invalid chunk dimensionality: {key}")
            if any(o < 0 or s <= 0 or o + s > bound for o, s, bound in zip(offsets, sizes, shape, strict=True)):
                raise ValueError(f"chunk outside DCP shape: {key}")
            for old_offsets, old_sizes in boxes:
                if all(
                    max(a, b) < min(a + sa, b + sb)
                    for a, sa, b, sb in zip(offsets, sizes, old_offsets, old_sizes, strict=True)
                ):
                    raise ValueError(f"overlapping DCP chunks: {key}")
            boxes.append((offsets, sizes))
            volume += math.prod(sizes)
        if volume != total:
            raise ValueError(f"incomplete DCP chunk coverage: {key}")
        tensors[key] = {"dtype": dtype, "shape": shape, "elements": total, "chunks": len(boxes)}
    placeholders = {key: row for key, row in by_name.items() if key not in tensors}
    for key, row in placeholders.items():
        if not key.endswith("[0]") or key[:-3] not in bytes_keys or row["shape"] != [0] or row["dtype"] != "uint8":
            raise ValueError(f"unaccounted non-storage inventory leaf: {key}")
    expected_bytes = {key[:-3] for key in placeholders}
    dropped_roots = set()
    for row in adapter["dropped_non_tensor_leaves"]:
        candidates = [key for key in bytes_keys if row["key"] == key or row["key"].startswith(key + "[")]
        if len(candidates) != 1:
            raise ValueError(f"unaccounted dropped leaf: {row['key']}")
        dropped_roots.add(candidates[0])
    if set(bytes_keys) != expected_bytes | dropped_roots:
        raise ValueError("unaccounted DCP byte container")
    if adapter["sanitized_tensor_count"] != len(rows) or adapter["sanitized_tensor_keys"] != len(rows):
        raise ValueError("adapter/inventory tensor count mismatch")
    model = sum(row["elements"] for key, row in tensors.items() if not key.startswith("optimizer."))
    optimizer = {key: row["elements"] for key, row in tensors.items() if key.startswith("optimizer.")}
    return {
        "status": "PASS_METADATA_COVERAGE",
        "tensor_storage_count": len(tensors),
        "model_storage_groups": len(tensors) - len(optimizer),
        "model_elements": model,
        "optimizer_elements_by_group": optimizer,
        "optimizer_total_elements": sum(optimizer.values()),
        "empty_placeholder_count": len(placeholders),
        "dropped_non_tensor_leaves": adapter["dropped_non_tensor_count"],
        "byte_container_roots_without_tensor_payload": sorted(dropped_roots),
        "tensors": tensors,
        "limit": "metadata/chunk/key/shape/dtype coverage; no independent reconversion or byte-container semantic decoding",
    }


def delta_series(off: list[float], on: list[float]) -> dict[str, Any]:
    if len(off) != len(on) or not off or any(not math.isfinite(value) for value in off + on):
        raise ValueError("missing/mismatched/nonfinite series")
    delta = [b - a for a, b in zip(off, on, strict=True)]
    return {
        "n_steps": len(off),
        "off_mean": sum(off) / len(off),
        "on_mean": sum(on) / len(on),
        "mean_signed_delta": sum(delta) / len(delta),
        "max_abs_delta": max(abs(value) for value in delta),
        "numerically_equal": off == on,
        "signed_deltas": delta,
    }


def audit(campaign: Path) -> dict[str, Any]:
    arms = {}
    for name in ARM_ORDER:
        arm = campaign / name
        native = parse_arm(arm, expected_steps=48)
        if not native.get("native_valid"):
            raise ValueError(f"invalid native extraction: {name}")
        adapter = json.loads((arm / "adapted/ADAPTER_RECORD.json").read_text())
        inventory = json.loads((arm / "inventory.json").read_text())
        manifest = json.loads((arm / "manifest.json").read_text())
        if (
            inventory.get("self_sha256") != canonical_sha256(inventory)
            or inventory.get("product_sha") != PRODUCT_SHA
            or inventory.get("arm_name") != name
            or adapter.get("arm_name") != name
            or manifest.get("product_sha") != PRODUCT_SHA
            or manifest.get("job_status") != "SUCCEEDED"
            or manifest.get("valid") is not True
            or inventory["lineage"]["adapter_record_sha256"] != sha256(arm / "adapted/ADAPTER_RECORD.json")
            or inventory["lineage"]["arm_manifest_sha256"] != sha256(arm / "manifest.json")
        ):
            raise ValueError(f"inventory/adapter/manifest identity or hash mismatch: {name}")
        root = Path(adapter["source_iteration_dir"]).resolve()
        if not root.is_relative_to((arm / "checkpoints").resolve()):
            raise ValueError("metadata outside owned checkpoint")
        meta = root / ".metadata"
        with meta.open("rb") as source:
            metadata = pickle.load(source)  # trusted, locally produced DCP metadata only
        arms[name] = {
            "inputs": {
                str(path.relative_to(arm)): sha256(path)
                for path in (
                    arm / "job.log",
                    meta,
                    arm / "inventory.json",
                    arm / "adapted/ADAPTER_RECORD.json",
                    arm / "manifest.json",
                )
            },
            "coverage": coverage(metadata, inventory, adapter),
            "native": native,
        }
    pairs = {}
    for number in (1, 2):
        off = arms[f"P-M{number}-off"]["native"]
        on = arms[f"P-M{number}-on"]["native"]
        rates_off, rates_on = off["learning_rate_series"], on["learning_rate_series"]
        if any(set(a) != set(b) for a, b in zip(rates_off, rates_on, strict=True)):
            raise ValueError("learning rate key sets differ")
        pairs[f"P-M{number}"] = {
            "loss": {"status": "UNSCORED", **delta_series(off["loss_series"], on["loss_series"])},
            "grad_norm": {"status": "UNSCORED", **delta_series(off["grad_norm_series"], on["grad_norm_series"])},
            "learning_rates_equal": rates_off == rates_on,
            "token_series_equal": off["token_series"] == on["token_series"],
            "step_ids_equal": off["native_step_ids"] == on["native_step_ids"],
            "updates": [off["update_count"], on["update_count"]],
            "numeric_nan_inf_count": len(off["nan_inf_findings"]) + len(on["nan_inf_findings"]),
        }
    return {
        "schema": "C2_NATIVE_SECONDARY_AUDIT/v1",
        "scope": "metadata coverage and descriptive native-series audit, not overall C2 acceptance",
        "product_sha": PRODUCT_SHA,
        "loss_grad_acceptance": "UNSCORED_NO_PRE_ON_FROZEN_BAND",
        "arms": arms,
        "pairs": pairs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("refusing to overwrite an existing audit")
    result = audit(args.campaign.resolve())
    result["tool_sha256"] = sha256(Path(__file__))
    result["self_sha256"] = canonical_sha256(result)
    args.out.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
