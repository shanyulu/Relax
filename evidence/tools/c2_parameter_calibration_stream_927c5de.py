#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Memory-bounded executor of the frozen C2 OFF/OFF calibration formula.

The committed ``c2_parameter_calibration_927c5de.py`` loads all four
schema-2 inventories eagerly as Python tuples. On this campaign's checkpoint
layout that is four times ~2.38B float values, i.e. ~375 GiB of anonymous
memory, while the 3090 host's container cgroup caps memory at 360 GiB. Two
telemetry-instrumented attempts were killed externally (SIGKILL, rc=137) at
226 GiB and 345 GiB RSS with the page cache fully evicted and no cgroup
``oom_kill`` recorded, proving the eager layout cannot complete on this
host regardless of tuning.

This executor computes the identical preregistered quantity with the
identical code: per-tensor max-abs-delta per fixed contrast is evaluated by
the original ``_pair_deltas`` from the committed calibration module, invoked
one tensor pair at a time (peak ~50 GiB). Arm/inventory identity, lineage
and payload-hash validation are the pinned runner's own
``validate_inventory_lineage``. The emitted ``P_CALIBRATION_RESULT.json``
is schema- and hash-identical to what the eager tool would produce:
``tol(t) = 2 x max(|C1-C2|, |C3-C4|)`` frozen before any ON exposure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    for name in ("c1", "c2", "c3", "c4"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        from c2_parameter_calibration_927c5de import _pair_deltas
        from c2_parameter_campaign_927c5de import load_lock, validate_inventory_lineage
        from c2_parameter_verdict_927c5de import Tensor, canonical_sha256, normalize_dtype, read_npy

        if args.out.exists():
            raise ValueError(f"refusing to overwrite {args.out}")
        lock = load_lock(args.lock)
        if lock["STAGE"] != "CALIBRATION":
            raise ValueError("calibration builder requires a calibration lock")
        identity = {**lock, "LOCK_SHA256": sha256_file(args.lock)}
        paths = {"P-C1-off": args.c1, "P-C2-off": args.c2, "P-C3-off": args.c3, "P-C4-off": args.c4}
        inventories: dict[str, dict[str, Any]] = {}
        for name, path in paths.items():
            validate_inventory_lineage(path, args.campaign / name, lock, identity["LOCK_SHA256"])
            raw = json.loads(path.read_text())
            required = {
                "arm_name": name,
                "product_sha": identity["PRODUCT_SHA"],
                "protocol_sha256": identity["PROTOCOL_SHA256"],
                "recipe_sha256": identity["RECIPE_SHA256"],
                "dataset_sha256": identity["DATASET_SHA256"],
                "env_fingerprint_sha256": identity["ENV_FINGERPRINT_SHA256"],
                "comparator_sha256": identity["COMPARATOR_SHA256"],
                "lock_sha256": identity["LOCK_SHA256"],
            }
            if any(raw.get(key) != expected for key, expected in required.items()):
                raise ValueError(f"{name}: inventory identity drift")
            if raw.get("self_sha256") != canonical_sha256(raw):
                raise ValueError(f"{name}: inventory self hash mismatch")
            inventories[name] = {"path": path, "raw": raw}
            print(f"validated lineage + identity: {name}", flush=True)

        def contrast(left_arm: str, right_arm: str) -> dict[str, float]:
            left = {entry["name"]: entry for entry in inventories[left_arm]["raw"]["tensors"]}
            right = {entry["name"]: entry for entry in inventories[right_arm]["raw"]["tensors"]}
            if set(left) != set(right):
                raise ValueError("OFF/OFF tensor key sets differ")
            output: dict[str, float] = {}
            left_base = inventories[left_arm]["path"].parent
            right_base = inventories[right_arm]["path"].parent
            for name in sorted(left):
                a, b = left[name], right[name]
                if a.get("shape") != b.get("shape") or a.get("dtype") != b.get("dtype"):
                    raise ValueError(f"{name}: OFF/OFF shape/dtype mismatch")
                dtype = normalize_dtype(a.get("dtype"))
                payload_a = (left_base / str(a.get("npy", ""))).resolve()
                payload_b = (right_base / str(b.get("npy", ""))).resolve()
                if not payload_a.is_relative_to(left_base.resolve()) or not payload_b.is_relative_to(
                    right_base.resolve()
                ):
                    raise ValueError(f"{name}: tensor payload escapes its inventory directory")
                npy_dtype_a, npy_shape_a, values_a = read_npy(payload_a)
                npy_dtype_b, npy_shape_b, values_b = read_npy(payload_b)
                rep_a = normalize_dtype(a.get("payload_dtype", dtype))
                rep_b = normalize_dtype(b.get("payload_dtype", dtype))
                if (
                    npy_dtype_a != rep_a
                    or npy_shape_a != tuple(a.get("shape"))
                    or (dtype != rep_a and dtype != "bfloat16")
                    or npy_dtype_b != rep_b
                    or npy_shape_b != tuple(b.get("shape"))
                ):
                    raise ValueError(f"{name}: npy metadata differs from inventory")
                # The committed whole-arm _pair_deltas, invoked one tensor
                # pair at a time: identical comparison code, bounded memory.
                per_tensor = _pair_deltas(
                    {name: Tensor(name, tuple(a["shape"]), dtype, values_a)},
                    {name: Tensor(name, tuple(b["shape"]), dtype, values_b)},
                )
                if name in per_tensor:
                    output[name] = per_tensor[name]
                del values_a, values_b, per_tensor
            return output

        first = contrast("P-C1-off", "P-C2-off")
        print("contrast P-C1/P-C2 complete", flush=True)
        second = contrast("P-C3-off", "P-C4-off")
        print("contrast P-C3/P-C4 complete", flush=True)
        if set(first) != set(second):
            raise ValueError("OFF/OFF contrasts have different tensor inventories")
        tolerances = {name: 2.0 * max(first[name], second[name]) for name in sorted(first)}
        table_sha = hashlib.sha256(json.dumps(tolerances, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        payload = {
            "status": "FROZEN_OFF_ONLY",
            "product_sha": identity["PRODUCT_SHA"],
            "protocol_sha256": identity["PROTOCOL_SHA256"],
            "PRODUCT_SHA": identity["PRODUCT_SHA"],
            "RECIPE_SHA256": identity["RECIPE_SHA256"],
            "DATASET_SHA256": identity["DATASET_SHA256"],
            "ENV_FINGERPRINT_SHA256": identity["ENV_FINGERPRINT_SHA256"],
            "PROTOCOL_SHA256": identity["PROTOCOL_SHA256"],
            "COMPARATOR_SHA256": identity["COMPARATOR_SHA256"],
            "ADAPTER_SHA256": identity["ADAPTER_SHA256"],
            "calibration_lock_sha256": identity["LOCK_SHA256"],
            "expected_steps": identity["EXPECTED_STEPS"],
            "inventory_sha256": {name: sha256_file(item["path"]) for name, item in inventories.items()},
            "contrast_max_abs_delta": {"P-C1/P-C2": first, "P-C3/P-C4": second},
            "tensor_tolerances": tolerances,
            "tolerance_table_sha256": table_sha,
            "self_sha256": None,
        }
        payload["self_sha256"] = canonical_sha256(payload)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(f"wrote {args.out} (self-sha {payload['self_sha256'][:12]})", flush=True)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
