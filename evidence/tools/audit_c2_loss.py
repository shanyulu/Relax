# Copyright (c) 2026 Relax Authors. All Rights Reserved.

"""Freeze OFF-only loss calibration, then compare historical paired ON arms.

This does not promote historical data to a newer product revision or infer
checkpoint equality. The freeze phase never opens ON logs.
"""

import argparse
import hashlib
import json
import statistics
from pathlib import Path

from extract_c2_native import parse_arm


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_arm(root: Path, name: str) -> dict:
    arm = parse_arm(root / name, expected_steps=48)
    if not arm.get("native_valid"):
        raise ValueError(f"invalid native metrics: {name}: {arm.get('extraction_errors')}")
    manifest = json.loads((root / name / "manifest.json").read_text())
    arm["product_sha"] = manifest["git"]["commit"]
    arm["dataset_sha256"] = manifest["dataset_sha256"]
    arm["job_log_sha256"] = digest(root / name / "job.log")
    return arm


def freeze(root: Path) -> dict:
    arms = {f"S{i}-off": read_arm(root, f"S{i}-off") for i in range(1, 7)}
    if len({(a["product_sha"], a["dataset_sha256"]) for a in arms.values()}) != 1:
        raise ValueError("OFF arms do not share product and dataset")
    first, second = arms["S1-off"]["loss_series"], arms["S2-off"]["loss_series"]
    deltas = [b - a for a, b in zip(first, second)]
    floor = abs(statistics.mean(first + second)) * 0.005
    return {
        "status": "FROZEN_OFF_ONLY_HISTORICAL",
        "calibration": ["S1-off", "S2-off"],
        "selection": "First two OFF sessions; selected before inspecting ON loss, after historical timing results were public.",
        "formula": "[min(min(S2-S1), -0.005*abs(mean(S1+S2))), max(max(S2-S1), +0.005*abs(mean(S1+S2)))]",
        "band": [min(min(deltas), -floor), max(max(deltas), floor)],
        "off_off_delta_range": [min(deltas), max(deltas)],
        "floor": floor,
        "arms": arms,
        "limitation": "48-step historical e961661 logs; SAVE=0, no checkpoint equivalence. Not final-code acceptance.",
    }


def compare(root: Path, frozen: dict) -> dict:
    low, high = frozen["band"]
    pairs = {}
    for i in range(1, 7):
        off = frozen["arms"][f"S{i}-off"]
        if digest(root / f"S{i}-off" / "job.log") != off["job_log_sha256"]:
            raise ValueError("OFF input changed after freeze")
        on = read_arm(root, f"S{i}-on")
        if (on["product_sha"], on["dataset_sha256"]) != (off["product_sha"], off["dataset_sha256"]):
            raise ValueError("ON/OFF provenance mismatch")
        delta = [b - a for a, b in zip(off["loss_series"], on["loss_series"])]
        pairs[f"S{i}"] = {
            "product_sha": on["product_sha"],
            "on_log_sha256": on["job_log_sha256"],
            "loss_delta": delta,
            "outside_band_steps": [j for j, value in enumerate(delta) if not low <= value <= high],
            "max_abs_loss_delta": max(map(abs, delta)),
            "max_abs_grad_norm_delta": max(
                abs(b - a) for a, b in zip(off["grad_norm_series"], on["grad_norm_series"])
            ),
            "learning_rates_equal": off["learning_rate_series"] == on["learning_rate_series"],
            "token_series_equal": off["token_series"] == on["token_series"],
        }
    return {
        "status": "PARTIAL_HISTORICAL_ONLY",
        "band": frozen["band"],
        "pairs": pairs,
        "checkpoint_equivalence": "NOT_MEASURED",
        "overlap": "NOT_MEASURED",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["freeze", "compare"])
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("refusing to overwrite an existing audit")
    if args.mode == "freeze":
        result = freeze(args.campaign)
    else:
        if args.freeze is None:
            parser.error("compare requires --freeze")
        result = compare(args.campaign, json.loads(args.freeze.read_text()))
        result["freeze_sha256"] = digest(args.freeze)
    args.out.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
