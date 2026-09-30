#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Execute the original calibration builder with validated lazy inventories."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import c2_parameter_calibration_927c5de as frozen_builder
import c2_parameter_verdict_927c5de as frozen
from c2_parameter_bounded_927c5de import Inventory, sha256_file
from c2_parameter_campaign_927c5de import load_lock, validate_inventory_lineage


def build(paths: dict[str, Path], identity: dict) -> dict:
    inventories = {}
    for arm, path in paths.items():
        raw = frozen.load_json(path, "checkpoint inventory")
        required = {
            "arm_name": arm,
            "product_sha": identity["PRODUCT_SHA"],
            "protocol_sha256": identity["PROTOCOL_SHA256"],
            "recipe_sha256": identity["RECIPE_SHA256"],
            "dataset_sha256": identity["DATASET_SHA256"],
            "env_fingerprint_sha256": identity["ENV_FINGERPRINT_SHA256"],
            "comparator_sha256": identity["COMPARATOR_SHA256"],
            "lock_sha256": identity["LOCK_SHA256"],
        }
        if any(raw.get(key) != expected for key, expected in required.items()):
            raise ValueError(f"{arm}: inventory identity drift")
        inventories[arm] = {
            "path": path,
            "raw": raw,
            "tensors": Inventory(
                path, product_sha=identity["PRODUCT_SHA"], protocol_sha256=identity["PROTOCOL_SHA256"]
            ),
        }
    return frozen_builder.build_calibration(inventories, identity)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    for name in ("c1", "c2", "c3", "c4"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit("refusing to overwrite calibration")
    try:
        lock = load_lock(args.lock)
        if lock["STAGE"] != "CALIBRATION":
            raise ValueError("calibration builder requires a calibration lock")
        lock_sha = sha256_file(args.lock)
        identity = {**lock, "LOCK_SHA256": lock_sha}
        paths = {f"P-C{n}-off": getattr(args, f"c{n}") for n in (1, 2, 3, 4)}
        for arm, path in paths.items():
            validate_inventory_lineage(path, args.campaign / arm, lock, lock_sha)
        result = build(paths, identity)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x") as out:
            out.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    except (ValueError, OSError, frozen.InvalidError, frozen.IncompleteError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
