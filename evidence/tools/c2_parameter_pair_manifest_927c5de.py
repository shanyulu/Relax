#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Bind OFF/ON by treatment labels, never by chronological AB/BA order."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from c2_parameter_bounded_927c5de import sha256_file
from c2_parameter_campaign_927c5de import load_lock
from c2_parameter_verdict_927c5de import read_calibration


def build(campaign: Path, calibration_path: Path, lock_path: Path) -> list[Path]:
    lock = load_lock(lock_path)
    calibration, calibration_sha = read_calibration(calibration_path)
    if lock["STAGE"] != "MEASUREMENT" or calibration_sha != lock["CALIBRATION_RESULT_SHA256"]:
        raise ValueError("measurement/calibration binding mismatch")
    if calibration["product_sha"] != lock["PRODUCT_SHA"] or calibration["protocol_sha256"] != lock["PROTOCOL_SHA256"]:
        raise ValueError("calibration identity mismatch")
    outputs = [campaign / f"P-M{number}_PAIR_MANIFEST.json" for number in (1, 2)]
    if any(path.exists() for path in outputs):
        raise ValueError("refusing to overwrite pair manifests")
    payloads = []
    for number in (1, 2):
        pair_id = f"P-M{number}"
        inventories = {side: campaign / f"{pair_id}-{side}" / "inventory.json" for side in ("off", "on")}
        for side, path in inventories.items():
            raw = json.loads(path.read_text())
            if raw.get("arm_name") != f"{pair_id}-{side}" or raw.get("lock_sha256") != sha256_file(lock_path):
                raise ValueError("inventory treatment/lock mismatch")
        payloads.append(
            {
                "pair_id": pair_id,
                "off_arm": f"{pair_id}-off",
                "on_arm": f"{pair_id}-on",
                "product_sha": lock["PRODUCT_SHA"],
                "protocol_sha256": lock["PROTOCOL_SHA256"],
                "calibration_sha256": calibration_sha,
                "measurement_lock_sha256": sha256_file(lock_path),
                **{f"{side}_inventory": str(path.relative_to(campaign)) for side, path in inventories.items()},
                **{f"{side}_inventory_sha256": sha256_file(path) for side, path in inventories.items()},
            }
        )
    for path, payload in zip(outputs, payloads):
        with path.open("x") as out:
            out.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    args = parser.parse_args()
    build(args.campaign, args.calibration, args.lock)


if __name__ == "__main__":
    main()
