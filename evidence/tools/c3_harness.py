#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""External C3 harness: non-invasive visibility-latency observer.

Watches an ON arm's RELAX_STRAGGLER_OUTPUT_DIR (filesystem growth = persist /
verdict visibility) and the Ray JOB-DRIVER log (append-only on disk, read
directly — NOT via the dashboard API, whose polling would add its own
staleness). Zero footprint on the training path.

Per C3_HARNESS_DESIGN_A48A23B.md the PRIMARY metric is the RAW
external-observer visibility latency; no constant subtraction. A --control
run (empty dir) characterises harness overhead separately and is never
subtracted from primary numbers.

Clock discipline: every event records BOTH time.time() (wall) and
time.monotonic() (mono). Log anchors additionally carry the EMBEDDED product
timestamp parsed from the line, so latency arithmetic can be done either
harness-side (read-time) or product-side (embedded) and the two are
distinguishable in the output.

Events:
  persist_grow     - growth of a straggler_*.jsonl file in the watch dir
  verdict_visible  - growth of a *verdict* file (subset of persist_grow)
  log_line         - a watched driver-log line (step/straggler/perf markers),
                     with embedded ts when parseable
  perf_write       - a 'perf N:' line containing 'straggler' (platform write)

Usage:
  python c3_harness.py --watch <arm_dir> \
      --driver-log /tmp/ray/session_latest/logs/job-driver-<id>.log \
      --out events.json [--control] [--duration 3600] [--poll-s 0.2]
"""

import argparse
import json
import re
import time
from pathlib import Path

VERDICT_GLOBS = ("**/straggler_verdicts.jsonl",)
PERSIST_GLOBS = ("**/straggler_verdicts.jsonl", "**/straggler_windows.jsonl", "**/straggler_envelopes.jsonl")

TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[,.]\d{3})")
WATCH_MARKERS = ("perf ", "straggler", "training step", "training completed", "iteration")


def snapshot_sizes(root: Path):
    snap = {}
    for pattern in PERSIST_GLOBS:
        for path in root.glob(pattern):
            try:
                snap[str(path)] = path.stat().st_size
            except OSError:
                pass
    return snap


def parse_wall_ts(line: str):
    match = TS_RE.search(line)
    if not match:
        return None
    raw = match.group(1).replace(",", ".")
    try:
        import datetime

        return datetime.datetime.strptime(raw, "%Y-%m-%d %H:%M:%S.%f").timestamp()
    except ValueError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--watch", type=Path, required=True)
    ap.add_argument("--driver-log", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--control", action="store_true")
    ap.add_argument("--duration", type=float, default=3600.0)
    ap.add_argument("--poll-s", type=float, default=0.2)
    args = ap.parse_args()

    if args.out.exists():
        raise SystemExit("refusing to overwrite an existing event log")

    events = []
    t_start = time.monotonic()
    sizes = {} if args.control else snapshot_sizes(args.watch)
    lines_seen = 0
    loop_count = 0
    max_poll_s = 0.0

    while (time.monotonic() - t_start) < args.duration:
        poll_t0 = time.monotonic()
        loop_count += 1
        wall_now = time.time()

        if not args.control:
            new = snapshot_sizes(args.watch)
            for path, size in new.items():
                old = sizes.get(path, 0)
                if size > old:
                    entry = {
                        "event": "persist_grow",
                        "wall": wall_now,
                        "mono": poll_t0,
                        "path": path,
                        "delta_bytes": size - old,
                        "file": Path(path).name,
                    }
                    events.append(entry)
                    if "verdict" in path:
                        events.append({**entry, "event": "verdict_visible"})
            sizes = new

        if args.driver_log and args.driver_log.exists():
            try:
                with args.driver_log.open("r", errors="replace") as fh:
                    lines = fh.readlines()
            except OSError:
                lines = []
            for line in lines[lines_seen:]:
                if any(marker in line for marker in WATCH_MARKERS):
                    events.append(
                        {
                            "event": "log_line",
                            "wall": wall_now,
                            "mono": poll_t0,
                            "embedded_wall": parse_wall_ts(line),
                            "line": line.strip()[:300],
                            "kind": (
                                "perf_write"
                                if "perf " in line and "straggler" in line
                                else ("straggler" if "straggler" in line else "step")
                            ),
                        }
                    )
            lines_seen = len(lines)

        elapsed_poll = time.monotonic() - poll_t0
        max_poll_s = max(max_poll_s, elapsed_poll)
        sleep_for = max(0.0, args.poll_s - elapsed_poll)
        time.sleep(sleep_for)

    payload = {
        "harness": "c3_external_observer_v2",
        "mode": "control" if args.control else "observing",
        "watch": str(args.watch),
        "driver_log": str(args.driver_log) if args.driver_log else None,
        "poll_s_target": args.poll_s,
        "poll_s_max_observed": round(max_poll_s, 4),
        "loop_count": loop_count,
        "duration_mono_s": time.monotonic() - t_start,
        "event_count": len(events),
        "events": events,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        f"mode={payload['mode']} loops={loop_count} max_poll={max_poll_s*1000:.1f}ms "
        f"events={len(events)} duration={payload['duration_mono_s']:.1f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
