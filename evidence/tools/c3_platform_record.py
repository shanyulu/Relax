#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Extract the perf/straggler/* platform record from an arm's tensorboard.

The straggler metrics merge into log_dict AFTER the 'perf N:' text log line
is emitted (train_metric_utils.log_perf_data_raw logs first, merges second,
then hands log_dict to tracking_utils.log) — so the text log NEVER shows
perf/straggler/* keys; the durable platform record is the tensorboard event
file. This tool extracts that record.
"""

import argparse
import json
from pathlib import Path

from tensorboard.backend.event_processing.event_accumulator import EventAccumulator


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arm", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        raise SystemExit("refusing to overwrite an existing extraction")

    records = {}
    for ev in sorted(args.arm.rglob("events.out.tfevents.*")):
        acc = EventAccumulator(str(ev.parent), size_guidance={"scalars": 0})
        acc.Reload()
        for tag in acc.Tags().get("scalars", []):
            if "straggler" in tag.lower():
                records[tag] = [
                    {"step": s.step, "value": s.value, "wall_time": s.wall_time}
                    for s in acc.Scalars(tag)
                ]
    payload = {
        "arm": str(args.arm),
        "scalar_series": len(records),
        "series": records,
    }
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    active = records.get("perf/straggler/active_stragglers", [])
    print(
        f"series={len(records)} steps_with_active={sum(1 for p in active if p['value'] > 0)} "
        f"max_active={max((p['value'] for p in active), default=0):.0f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
