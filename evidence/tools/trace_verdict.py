#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Trace-campaign verdict per TRACE_LOCK frozen rule.

Inputs: the four arm overlap_metrics.json files. Rule (frozen in TRACE_LOCK
before any ON trace ran):
  delta_frozen = 2 x max |OFF/OFF pairwise overlap_ratio delta|
  PASS iff overlap_ratio(ON) >= overlap_ratio(OFF reference) - delta_frozen
       AND new_global_sync(ON) - new_global_sync(OFF reference) <= 0
The global-sync comparison is reported together with the OFF/OFF sync
variance so a natural-run variance is visible rather than hidden.
"""

import argparse
import json
from pathlib import Path


def load(arm_dir: Path):
    return json.loads((arm_dir / "overlap_metrics.json").read_text())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        raise SystemExit("refusing to overwrite an existing verdict")

    arms = {name: load(args.base / name) for name in ("TR0-off", "TR0-off2", "TR1-off", "TR1-on")}
    ratios = {k: v["overlap_ratio_total"] for k, v in arms.items()}
    syncs = {k: v["global_sync_count_total"] for k, v in arms.items()}
    off_values = [ratios["TR0-off"], ratios["TR0-off2"]]
    off_off_deltas = [abs(a - b) for i, a in enumerate(off_values) for b in off_values[i + 1:]]
    delta_frozen = 2.0 * max(off_off_deltas) if off_off_deltas else 0.0
    off_reference = ratios["TR1-off"]
    on_value = ratios["TR1-on"]
    sync_off_off_deltas = [abs(syncs["TR0-off"] - syncs["TR0-off2"])]
    sync_delta_on_off = syncs["TR1-on"] - syncs["TR1-off"]

    overlap_ok = on_value >= off_reference - delta_frozen
    sync_ok = sync_delta_on_off <= 0
    verdict = "PASS" if (overlap_ok and sync_ok) else "NOT_PASS"

    payload = {
        "verdict": verdict,
        "rule": "overlap_ratio(ON) >= overlap_ratio(OFF ref) - 2x max|OFF/OFF delta| AND delta_global_sync(ON-OFF) <= 0",
        "overlap_ratio": ratios,
        "off_off_pairwise_deltas": off_off_deltas,
        "delta_frozen": delta_frozen,
        "off_reference_arm": "TR1-off",
        "overlap_pass": overlap_ok,
        "global_sync_counts": syncs,
        "off_off_sync_deltas": sync_off_off_deltas,
        "on_off_sync_delta": sync_delta_on_off,
        "sync_pass": sync_ok,
        "note": (
            "global-sync counts include natural run-to-run variance (OFF/OFF delta shown); "
            "the frozen rule compares ON vs the same-design OFF reference arm"
        ),
        "ranks_profiled": {k: v["ranks_profiled"] for k, v in arms.items()},
    }
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({k: payload[k] for k in ("verdict", "overlap_ratio", "delta_frozen", "global_sync_counts", "overlap_pass", "sync_pass")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
