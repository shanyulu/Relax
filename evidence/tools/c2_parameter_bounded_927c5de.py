#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Bounded-memory execution of the frozen parameter comparison semantics."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import c2_parameter_verdict_927c5de as frozen


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Inventory(dict):
    """Validate inventory metadata once; materialize only the requested
    tensor."""

    def __init__(self, path: Path, *, product_sha: str, protocol_sha256: str, **identity: Any):
        self.path = path
        raw = frozen.load_json(path, "checkpoint inventory")
        if raw.get("product_sha") != product_sha or raw.get("protocol_sha256") != protocol_sha256:
            raise frozen.InvalidError(f"checkpoint inventory identity mismatch: {path}")
        if raw.get("self_sha256") != frozen.canonical_sha256(raw):
            raise frozen.InvalidError(f"checkpoint inventory self hash mismatch: {path}")
        arm = identity.get("arm_name")
        if arm is not None and raw.get("arm_name") != arm:
            raise frozen.InvalidError(f"checkpoint inventory arm mismatch: expected {arm}: {path}")
        lock_sha = identity.get("measurement_lock_sha256")
        if lock_sha is not None and raw.get("lock_sha256") != lock_sha:
            raise frozen.InvalidError(f"checkpoint inventory measurement lock mismatch: {path}")
        entries = raw.get("tensors")
        if not isinstance(entries, list) or not entries:
            raise frozen.IncompleteError(f"checkpoint inventory has no tensors: {path}")
        super().__init__()
        for entry in entries:
            if not isinstance(entry, dict):
                raise frozen.InvalidError(f"invalid tensor entry in {path}")
            name = entry.get("name")
            if not isinstance(name, str) or not name or name in self:
                raise frozen.InvalidError(f"missing or duplicate tensor name in {path}")
            if not isinstance(entry.get("shape"), list):
                raise frozen.InvalidError(f"missing tensor shape for {name}")
            frozen.value_count(tuple(entry["shape"]))
            frozen.normalize_dtype(entry.get("dtype"))
            self[name] = entry

    def __getitem__(self, name: str) -> frozen.Tensor:
        entry = super().__getitem__(name)
        shape = tuple(entry["shape"])
        count = frozen.value_count(shape)
        dtype = frozen.normalize_dtype(entry.get("dtype"))
        if "values" in entry:
            raw = entry["values"]
            if not isinstance(raw, list) or len(raw) != count:
                raise frozen.IncompleteError(f"missing or incomplete values for tensor {name}")
            values = tuple(raw)
        elif "npy" in entry:
            path = frozen.resolve_relative(self.path.parent, entry["npy"], f"npy payload for {name}")
            if not path.is_file():
                raise frozen.IncompleteError(f"missing tensor payload: {path}")
            if frozen.require_sha(entry.get("payload_sha256"), f"npy hash for {name}") != sha256_file(path):
                raise frozen.InvalidError(f"npy payload hash mismatch for {name}")
            npy_dtype, npy_shape, values = frozen.read_npy(path)
            representation = frozen.normalize_dtype(entry.get("payload_dtype", dtype))
            if npy_dtype != representation or npy_shape != shape or (dtype != representation and dtype != "bfloat16"):
                raise frozen.InvalidError(f"npy metadata differs from inventory for tensor {name}")
        else:
            raise frozen.IncompleteError(f"missing payload for tensor {name}")
        if dtype in frozen.FLOAT_DTYPES:
            try:
                if not all(math.isfinite(float(value)) for value in values):
                    raise frozen.InvalidError(f"non-finite floating tensor {name}")
            except (TypeError, ValueError) as exc:
                raise frozen.InvalidError(f"non-numeric floating tensor {name}") from exc
        return frozen.Tensor(name, shape, dtype, values)


def compare_pair(pair_path: Path, calibration: dict, calibration_sha: str) -> tuple[dict, list[str]]:
    pair = frozen.load_json(pair_path, "pair manifest")
    product = calibration["product_sha"]
    protocol = calibration["protocol_sha256"]
    if pair.get("product_sha") != product or pair.get("protocol_sha256") != protocol:
        raise frozen.InvalidError(f"pair identity mismatch: {pair_path}")
    if pair.get("calibration_sha256") != calibration_sha:
        raise frozen.InvalidError(f"pair does not bind the supplied calibration: {pair_path}")
    lock_sha = frozen.require_sha(pair.get("measurement_lock_sha256"), "measurement lock hash")
    pair_id = pair.get("pair_id")
    if pair_id not in {"P-M1", "P-M2"}:
        raise frozen.InvalidError(f"invalid pair_id: {pair_path}")
    paths = {
        side: frozen.resolve_relative(
            pair_path.parent, pair.get(f"{side}_inventory"), f"{side.upper()} inventory for {pair_id}"
        )
        for side in ("off", "on")
    }
    if paths["off"] == paths["on"]:
        raise frozen.InvalidError(f"{pair_id}: ON and OFF cannot reference the same inventory")
    inventories = {}
    for side, path in paths.items():
        if not path.is_file():
            raise frozen.IncompleteError(f"missing {side.upper()} inventory for {pair_id}: {path}")
        pinned = frozen.require_sha(pair.get(f"{side}_inventory_sha256"), f"{side} inventory hash for {pair_id}")
        if sha256_file(path) != pinned:
            raise frozen.InvalidError(f"{pair_id}: {side} inventory hash mismatch")
        inventories[side] = Inventory(
            path,
            product_sha=product,
            protocol_sha256=protocol,
            arm_name=f"{pair_id}-{side}",
            measurement_lock_sha256=lock_sha,
        )
    off, on = inventories["off"], inventories["on"]
    tolerances = calibration["tensor_tolerances"]
    violations = []
    missing = []
    results = {}
    if set(off) != set(on):
        violations.append("tensor key set differs")
    for name in sorted(set(off) | set(on)):
        left = off[name] if name in off else None
        right = on[name] if name in on else None
        if left is None or right is None:
            results[name] = {"state": "MISSING_FROM_ONE_ARM"}
        elif left.shape != right.shape or left.dtype != right.dtype:
            violations.append(f"{name}: shape or dtype differs")
            results[name] = {
                "state": "METADATA_MISMATCH",
                "off": {"shape": left.shape, "dtype": left.dtype},
                "on": {"shape": right.shape, "dtype": right.dtype},
            }
        elif left.dtype in frozen.FLOAT_DTYPES and name not in tolerances:
            missing.append(name)
            results[name] = {"state": "MISSING_FROZEN_TOLERANCE"}
        elif left.dtype in frozen.FLOAT_DTYPES:
            maximum = relative = 0.0
            exact = True
            for a, b in zip(left.values, right.values):
                delta = abs(float(a) - float(b))
                maximum = max(maximum, delta)
                relative = max(relative, delta / max(abs(float(a)), abs(float(b)), sys.float_info.min))
                exact = exact and a == b
            tolerance = tolerances[name]
            within = maximum <= tolerance
            results[name] = {
                "state": "PASS" if within else "NOT_PASS",
                "max_abs_delta": maximum,
                "max_rel_delta": relative,
                "tolerance": tolerance,
                "exact_equal": exact,
            }
            if not within:
                violations.append(f"{name}: {maximum} > {tolerance}")
        else:
            exact = left.values == right.values
            results[name] = {"state": "PASS" if exact else "NOT_PASS", "exact_equal": exact}
            if not exact:
                violations.append(f"{name}: non-floating payload differs")
        del left, right
    return {
        "pair_id": pair_id,
        "manifest_sha256": sha256_file(pair_path),
        "off_inventory_sha256": sha256_file(paths["off"]),
        "on_inventory_sha256": sha256_file(paths["on"]),
        "tensors": results,
        "violations": violations,
        "missing_tolerances": missing,
    }, violations


def run(args: argparse.Namespace) -> int:
    """Delegate result ordering, classification and serialization to the frozen
    tool.

    This is a single-process CLI adapter, not a concurrent library API.
    """
    original = frozen.compare_pair
    frozen.compare_pair = compare_pair
    try:
        return frozen.run(args)
    finally:
        frozen.compare_pair = original


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--calibration-result", type=Path, required=True)
    parser.add_argument("--pair-manifest", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit("refusing to overwrite an existing parameter verdict")
    import c2_parameter_campaign_927c5de as campaign

    original = frozen.compare_pair
    frozen.compare_pair = compare_pair
    try:
        return campaign._measurement_result(args)
    except (ValueError, OSError, frozen.InvalidError, frozen.IncompleteError) as exc:
        verdict = "INCOMPLETE" if isinstance(exc, (FileNotFoundError, frozen.IncompleteError)) else "INVALID"
        payload = frozen.result_payload(verdict, str(exc), calibration=args.calibration_result, pairs=[])
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return 1 if verdict == "INCOMPLETE" else 2
    finally:
        frozen.compare_pair = original


if __name__ == "__main__":
    sys.exit(main())
