#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""C3 evidence summariser: raw external-observer visibility latency.

Consumes the harness event log + the arm's straggler verdicts and produces
the C3 evidence record per C3_HARNESS_DESIGN_A48A23B.md §3:
  - EXTERNAL-OBSERVER VISIBILITY LATENCY distribution (RAW, p50/p95/p99/max)
  - real localized verdict (rank/stage/reason/count)
  - tail window / silent tail accounting
  - platform record (perf-write lines seen by the harness)
No subtraction of harness overhead anywhere; the control run's loop cost is
reported alongside as context.
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

    # 1) visibility latency: for each verdict_visible event, the latency back to
    # the most recent log anchor (training-side) seen BEFORE it, and forward to
    # the next perf_write (platform-side) seen AFTER it.
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
        "metric_name": "EXTERNAL-OBSERVER VISIBILITY LATENCY (raw)",
        "interval_anchor_to_verdict_persist": dist(verdict_to_persist),
        "verdict_persist_to_platform_perf_write": dist(persist_to_perf),
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
            "note": "final-window verdicts present iff the last windows were judged before exit",
            "last_verdict_is_straggler_or_recovered": bool(verdicts) and verdicts[-1].get("kind") in ("straggler", "recovered"),
            "total_verdicts": len(verdicts),
        },
        "event_counts": {k: sum(1 for e in events if e["event"] == k or e.get("kind") == k) for k in ("persist_grow", "verdict_visible", "perf_write", "log_line")},
    }
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({k: payload[k] for k in ("interval_anchor_to_verdict_persist", "verdict_persist_to_platform_perf_write", "real_localized_verdict", "verdict_kind_counts")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
