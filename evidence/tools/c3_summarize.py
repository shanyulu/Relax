#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Summarise C3 records without inventing event-to-event latency.

Legacy file-growth observations cannot be joined to individual intervals or
verdicts. Retain their gaps for audit, but fail closed on latency and tail
proof.
"""

import argparse
import json
import statistics
from pathlib import Path


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[idx]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--events", type=Path, required=True)
    ap.add_argument("--control", type=Path, required=True)
    ap.add_argument("--verdicts", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        raise SystemExit("refusing to overwrite an existing summary")

    ev = json.loads(args.events.read_text())
    ctl = json.loads(args.control.read_text())
    verdicts = [json.loads(l) for l in args.verdicts.read_text().splitlines() if l.strip()]

    # These are unpaired observations, not causal latency measurements.
    events = ev["events"]
    anchors = [e for e in events if e["event"] == "log_line" and e.get("kind") == "step"]
    persist = [e for e in events if e["event"] == "verdict_visible"]
    perf_writes = [e for e in events if e.get("kind") == "perf_write"]
    verdict_to_persist = []
    for p in persist:
        prev_anchor = None
        for a in anchors:
            if a["mono"] <= p["mono"]:
                prev_anchor = a
            else:
                break
        if prev_anchor is not None:
            verdict_to_persist.append(p["mono"] - prev_anchor["mono"])
    persist_to_perf = []
    for p in persist:
        nxt = next((w for w in perf_writes if w["mono"] >= p["mono"]), None)
        if nxt is not None:
            persist_to_perf.append(nxt["mono"] - p["mono"])

    def dist(values):
        if not values:
            return {"n": 0}
        return {
            "n": len(values),
            "p50_s": round(percentile(values, 0.50), 3),
            "p95_s": round(percentile(values, 0.95), 3),
            "p99_s": round(percentile(values, 0.99), 3),
            "max_s": round(max(values), 3),
            "mean_s": round(statistics.mean(values), 3),
        }

    straggler_verdicts = [v for v in verdicts if v.get("kind") == "straggler"]
    kinds = {}
    for v in verdicts:
        kinds[v.get("kind")] = kinds.get(v.get("kind"), 0) + 1

    payload = {
        "metric_name": "UNMATCHED LOG-TO-FILE OBSERVATION GAPS (not event latency)",
        "measurement_status": "UNMEASURED",
        "measurement_reason": "No event identity joins interval completion, verdict persistence and platform visibility",
        "unmatched_log_to_file_gap": dist(verdict_to_persist),
        "interval_anchor_to_verdict_persist": {"n": 0, "status": "UNMEASURED"},
        "verdict_persist_to_platform_perf_write": {"n": 0, "status": "UNMEASURED"},
        "harness_context": {
            "poll_s_target": ev.get("poll_s_target"),
            "poll_s_max_observed": ev.get("poll_s_max_observed"),
            "control_loop_cost_ms": round((ctl.get("loop_cost_s") or 0) * 1000, 3),
            "note": "control run characterises measurement overhead; NEVER subtracted from the primary numbers",
        },
        "real_localized_verdict": {
            "count": len(straggler_verdicts),
            "ranks": sorted({v.get("rank") for v in straggler_verdicts}),
            "labels": sorted({v.get("label") for v in straggler_verdicts})[:4],
            "reasons": sorted({v.get("reason") for v in straggler_verdicts}),
            "max_consecutive_windows": max((v.get("consecutive_windows") or 0 for v in straggler_verdicts), default=0),
            "max_deviation": max((v.get("deviation") or 0 for v in straggler_verdicts), default=0),
        },
        "verdict_kind_counts": kinds,
        "platform_record": {"perf_write_events_seen": len(perf_writes)},
        "tail_window": {
            "status": "UNVERIFIED",
            "note": "final-window verdicts present iff the last windows were judged before exit",
            "last_verdict_is_straggler_or_recovered": bool(verdicts)
            and verdicts[-1].get("kind") in ("straggler", "recovered"),
            "total_verdicts": len(verdicts),
        },
        "event_counts": {
            k: sum(1 for e in events if e["event"] == k or e.get("kind") == k)
            for k in ("persist_grow", "verdict_visible", "perf_write", "log_line")
        },
    }
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: payload[k]
                for k in (
                    "interval_anchor_to_verdict_persist",
                    "verdict_persist_to_platform_perf_write",
                    "real_localized_verdict",
                    "verdict_kind_counts",
                )
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
