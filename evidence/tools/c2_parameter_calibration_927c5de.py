#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Build the committed four-OFF C2 tensor tolerance result.

This module owns calibration only; it deliberately delegates all ON/OFF
verdicting to ``c2_parameter_verdict_927c5de.py``.  It requires the fixed
P-C1/P-C2 and P-C3/P-C4 contrasts and writes a non-overwriting self-hashed
result that is the sole object allowed to unlock the measurement lock.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def result_hash(payload: dict[str, Any]) -> str:
    from c2_parameter_verdict_927c5de import canonical_sha256

    return canonical_sha256(payload)


def load_inventory(path: Path, identity: dict[str, Any], arm_name: str) -> dict[str, Any]:
    from c2_parameter_verdict_927c5de import read_inventory

    raw = json.loads(path.read_text())
    required = {
        "arm_name": arm_name,
        "product_sha": identity["PRODUCT_SHA"],
        "protocol_sha256": identity["PROTOCOL_SHA256"],
        "recipe_sha256": identity["RECIPE_SHA256"],
        "dataset_sha256": identity["DATASET_SHA256"],
        "env_fingerprint_sha256": identity["ENV_FINGERPRINT_SHA256"],
        "comparator_sha256": identity["COMPARATOR_SHA256"],
        "lock_sha256": identity["LOCK_SHA256"],
    }
    if any(raw.get(key) != expected for key, expected in required.items()):
        raise ValueError(f"{arm_name}: inventory identity drift")
    if (
        raw.get("self_sha256")
        != hashlib.sha256(
            json.dumps({**raw, "self_sha256": None}, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    ):
        raise ValueError(f"{arm_name}: inventory self hash mismatch")
    return {
        "raw": raw,
        "tensors": read_inventory(
            path, product_sha=identity["PRODUCT_SHA"], protocol_sha256=identity["PROTOCOL_SHA256"]
        ),
    }


def _pair_deltas(left: dict[str, Any], right: dict[str, Any]) -> dict[str, float]:
    if set(left) != set(right):
        raise ValueError("OFF/OFF tensor key sets differ")
    output: dict[str, float] = {}
    for name in sorted(left):
        a, b = left[name], right[name]
        if a.shape != b.shape or a.dtype != b.dtype:
            raise ValueError(f"{name}: OFF/OFF shape/dtype mismatch")
        if a.dtype == "bfloat16" or a.dtype.startswith(("<f", ">f")):
            if not all(math.isfinite(float(value)) for value in (*a.values, *b.values)):
                raise ValueError(f"{name}: non-finite calibration value")
            output[name] = max((abs(float(x) - float(y)) for x, y in zip(a.values, b.values)), default=0.0)
        elif a.values != b.values:
            raise ValueError(f"{name}: non-floating OFF/OFF value differs")
    return output


def build_calibration(inventories: dict[str, dict[str, Any]], identity: dict[str, Any]) -> dict[str, Any]:
    first = _pair_deltas(inventories["P-C1-off"]["tensors"], inventories["P-C2-off"]["tensors"])
    second = _pair_deltas(inventories["P-C3-off"]["tensors"], inventories["P-C4-off"]["tensors"])
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
    payload["self_sha256"] = result_hash(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    for name in ("c1", "c2", "c3", "c4"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        from c2_parameter_campaign_927c5de import load_lock, validate_inventory_lineage

        if args.out.exists():
            raise ValueError(f"refusing to overwrite {args.out}")
        lock = load_lock(args.lock)
        if lock["STAGE"] != "CALIBRATION":
            raise ValueError("calibration builder requires a calibration lock")
        identity = {**lock, "LOCK_SHA256": sha256_file(args.lock)}
        paths = {"P-C1-off": args.c1, "P-C2-off": args.c2, "P-C3-off": args.c3, "P-C4-off": args.c4}
        for name, path in paths.items():
            validate_inventory_lineage(path, args.campaign / name, lock, identity["LOCK_SHA256"])
        inventories = {name: {"path": path, **load_inventory(path, identity, name)} for name, path in paths.items()}
        result = build_calibration(inventories, identity)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
