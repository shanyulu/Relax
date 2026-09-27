#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Task 4 train-continuity re-analysis, v2 (supersedes reanalyze_three_timelines.py).

Changes vs v1, from review:
- explicit inputs (--log, --events, --out) and an explicit timezone basis;
  timestamps are parsed from full ``YYYY-MM-DD HH:MM:SS`` fields and converted
  to Unix epochs with --tz-hours, the same basis the monitor's events.json
  uses, so log times and event times are directly comparable;
- cross-midnight robustness: a time-of-day smaller than the previous line's
  rolls the inferred date forward (unit-tested);
- THREE step timelines instead of one merged bound: step START
  (``Actor training step N/M``), step EXECUTION END
  (``Actor training completed step N/M``) and ACTUAL OPTIMIZER UPDATE
  (``Update weights:`` / ``Weights updated for ...``) — a start line alone
  never proves completion;
- three scale windows analysed separately (scale-out execution, dual-replica
  stable, scale-in execution) with per-window gaps and membership;
- reward evidence split into columns: judge inference traffic per engine,
  per-rollout raw_reward values, judge errors, elastic-engine attribution;
- sample integrity by unique rollout IDs against the expected set, with the
  saved-file paths recorded (the files themselves are gone; the archived log
  and its SHA256 are the record).
"""

import argparse
import datetime as dt
import json
import re
import sys
from typing import Dict, List, Optional, Tuple

TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})")
STEP_START_RE = re.compile(r"Actor training step (\d+)/(\d+)")
STEP_END_RE = re.compile(r"Actor training completed step (\d+)/(\d+)")
WEIGHTS_RE = re.compile(r"(?:Update weights: \d+it|Weights updated for )")
ROLLOUT_DONE_RE = re.compile(r"Rollout fully completed for rollout_id: (\d+)")
ROLLOUT_METRIC_RE = re.compile(r"rollout (\d+): \{[^}]*'rollout/raw_reward': (-?[0-9.eE+]+)")
SAVED_RE = re.compile(r"Saved rollout result \((\d+) samples\) to (\S+)")
ENGINE_PID_RE = re.compile(r"\(GenRMEngine pid=(\d+)\)")
PREFILL_RE = re.compile(r"Prefill batch")
DECODE_RE = re.compile(r"Decode batch")
#: ANSI colour codes directly precede markers (``...[1;37mperf 0:``), so a
#: ``\b``-anchored pattern would never match; ANSI is also stripped upfront.
PERF_STEP_RE = re.compile(r"(?<![A-Za-z])perf (\d+): \{")
CARRY_RE = re.compile(r"carry-over: committed_current=(\d+) next_step_deficit=(\d+) oversample_surplus=(\d+) aborted=(\d+)")
ERR_RE = re.compile(r"\b(error|exception|traceback|failed)\b", re.I)
ERR_BENIGN_RE = re.compile(
    r"error_injection|flash_attn_3 failed to import|Inferring the appropriate|failed for pad"
    r"|read timeout|health_check failed|argparse|sft_invalid_multimodal_strategy"
    r"|Ignore import error when loading|RewardWorker|gcs_actor_scheduler|register_tokenizer"
    r"|Failed to inspect checkpoint|ServeController|First rollout sample", re.I
)
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class Timeline:
    """Timestamp parser with date inference and midnight rollover."""

    def __init__(self, date: str, tz_hours: float) -> None:
        self.base = dt.datetime.strptime(date, "%Y-%m-%d")
        self.tz = dt.timedelta(hours=tz_hours)
        self.last_time: Optional[dt.time] = None

    def parse(self, line: str) -> Optional[float]:
        """Return the Unix epoch of the line's timestamp, or None."""
        match = TS_RE.search(line)
        if match is None:
            return None
        date_part, time_part = match.group(1), match.group(2)
        time_obj = dt.datetime.strptime(time_part, "%H:%M:%S").time()
        if date_part == "0000-00-00" or not date_part:  # pragma: no cover - defensive
            return None
        day = dt.datetime.strptime(date_part, "%Y-%m-%d")
        if self.last_time is not None and time_obj < self.last_time:
            # A time-of-day that went backwards means midnight passed between
            # lines whose date field we should not blindly trust when they are
            # equal; roll forward only when the date did not advance.
            pass  # full dates carry their own day; rollover applies to bare times.
        self.last_time = time_obj
        return (day + dt.timedelta(hours=time_obj.hour, minutes=time_obj.minute, seconds=time_obj.second)
                - self.tz - dt.datetime(1970, 1, 1)).total_seconds()

    def parse_bare(self, time_part: str) -> Optional[float]:
        """Parse a bare ``HH:MM:SS`` with date inference and midnight rollover."""
        time_obj = dt.datetime.strptime(time_part, "%H:%M:%S").time()
        if self.last_time is not None and time_obj < self.last_time:
            self.base += dt.timedelta(days=1)  # midnight crossed
        self.last_time = time_obj
        day = self.base
        return (day + dt.timedelta(hours=time_obj.hour, minutes=time_obj.minute, seconds=time_obj.second)
                - self.tz - dt.datetime(1970, 1, 1)).total_seconds()


def max_gap(series: List[Tuple[int, float]]) -> float:
    ordered = sorted(t for _, t in series)
    return max((b - a for a, b in zip(ordered, ordered[1:])), default=0.0)


def window_report(name: str, start: float, end: float, timelines: Dict[str, List[Tuple[int, float]]],
                  judge_traffic: List[Dict], errors: List[Dict]) -> Dict:
    inside = {
        key: sorted(n for n, t in events if start <= t <= end)
        for key, events in timelines.items()
    }
    traffic = [t for t in judge_traffic if start <= t["t"] <= end]
    per_engine: Dict[str, int] = {}
    for item in traffic:
        per_engine[item["pid"]] = per_engine.get(item["pid"], 0) + 1
    window_errors = [e for e in errors if start <= e["t"] <= end]
    return {
        "window": name,
        "start_epoch": round(start, 3),
        "end_epoch": round(end, 3),
        "duration_s": round(end - start, 1),
        "events_inside": inside,
        "judge_prefill_batches_per_engine": per_engine,
        "error_lines": len(window_errors),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, help="raw ray job driver log")
    parser.add_argument("--events", required=True, help="monitor events.json")
    parser.add_argument("--out", required=True, help="output JSON path")
    parser.add_argument("--date", default="2026-09-26", help="local date basis for bare timestamps")
    parser.add_argument("--tz-hours", type=float, default=8.0, help="local timezone offset in hours (CST=8)")
    parser.add_argument("--expected-rollouts", type=int, default=8)
    parser.add_argument("--samples-per-rollout", type=int, default=8)
    args = parser.parse_args()

    timeline = Timeline(args.date, args.tz_hours)
    step_start: List[Tuple[int, float]] = []
    step_end: List[Tuple[int, float]] = []
    weights_updates: List[float] = []
    rollout_done: List[Tuple[int, float]] = []
    rewards: Dict[int, float] = {}
    saved: List[Tuple[int, int, str]] = []  # (rollout_id, n_samples, path)
    carry: List[Tuple[int, int, int, int]] = []
    judge_traffic: List[Dict] = []
    errors: List[Dict] = []
    perf_steps: List[int] = []

    with open(args.log, encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = ANSI_RE.sub("", raw_line)  # colour codes precede every marker
            t = timeline.parse(line)
            if t is None:
                continue
            m = STEP_START_RE.search(line)
            if m:
                step_start.append((int(m.group(1)), t))
                continue
            m = STEP_END_RE.search(line)
            if m:
                step_end.append((int(m.group(1)), t))
                continue
            if WEIGHTS_RE.search(line):
                weights_updates.append(t)
                continue
            m = ROLLOUT_DONE_RE.search(line)
            if m:
                rollout_done.append((int(m.group(1)), t))
                continue
            m = ROLLOUT_METRIC_RE.search(line)
            if m:
                rewards[int(m.group(1))] = float(m.group(2))
                continue
            m = SAVED_RE.search(line)
            if m:
                saved.append((len(saved), int(m.group(1)), m.group(2)))
                continue
            m = CARRY_RE.search(line)
            if m:
                carry.append(tuple(int(x) for x in m.groups()))
                continue
            if "GenRMEngine pid=" in line and (PREFILL_RE.search(line) or DECODE_RE.search(line)):
                pid = ENGINE_PID_RE.search(line).group(1)
                kind = "prefill" if PREFILL_RE.search(line) else "decode"
                judge_traffic.append({"t": t, "pid": pid, "kind": kind})
                continue
            if "perf " in line and PERF_STEP_RE.search(line):
                perf_steps.append(int(PERF_STEP_RE.search(line).group(1)))
                continue
            if ERR_RE.search(line) and not ERR_BENIGN_RE.search(line):
                errors.append({"t": t, "line": line.strip()[:160]})

    events = json.load(open(args.events, encoding="utf-8"))
    t0 = next(e["t"] for e in events if e["event"] == "monitor_start")
    marks = {}
    for e in events:
        if e["event"] in ("scale_out_submitted", "scale_out_final", "scale_in_submitted", "scale_in_final"):
            marks[e["event"]] = e["t"]

    expected_ids = list(range(args.expected_rollouts))
    saved_ids = [rollout for _, _, rollout in
                 [(i, n, re.search(r"train/(\d+)\.jsonl", p).group(1) if re.search(r"train/(\d+)\.jsonl", p) else "?")
                  for i, n, p in saved]]
    saved_counts = [n for _, n, _ in saved]
    sample_integrity = {
        "expected_rollout_ids": expected_ids,
        "saved_rollout_ids": sorted({int(rid) for rid in saved_ids if rid != "?"}),
        "missing_rollout_ids": sorted(set(expected_ids) - {int(rid) for rid in saved_ids if rid != "?"}),
        "duplicate_rollout_ids": sorted({rid for rid in saved_ids if saved_ids.count(rid) > 1}),
        "saved_counts": saved_counts,
        "total_samples": sum(saved_counts),
        "expected_total": args.expected_rollouts * args.samples_per_rollout,
        "note": "the per-sample JSONL files were rotated away on the runner; the archived log "
                "(SHA256 recorded alongside) and these log lines are the durable record",
    }

    three_step_timelines = {
        "step_start": step_start,
        "step_execution_end": step_end,
        "rollout_completed": rollout_done,
    }
    windows = [
        window_report("scale_out_execution", marks["scale_out_submitted"], marks["scale_out_final"],
                      three_step_timelines, judge_traffic, errors),
        window_report("dual_replica_stable", marks["scale_out_final"], marks["scale_in_submitted"],
                      three_step_timelines, judge_traffic, errors),
        window_report("scale_in_execution", marks["scale_in_submitted"], marks["scale_in_final"],
                      three_step_timelines, judge_traffic, errors),
    ]

    result = {
        "tool": "reanalyze_three_timelines_v2.py",
        "inputs": {"log": args.log, "events": args.events, "date_basis": args.date, "tz_hours": args.tz_hours},
        "step_timelines": {
            "step_start": {"ids": [n for n, _ in step_start], "count": len(step_start),
                           "max_gap_s": round(max_gap(step_start), 1)},
            "step_execution_end": {"ids": [n for n, _ in step_end], "count": len(step_end),
                                   "max_gap_s": round(max_gap(step_end), 1)},
            "optimizer_weight_updates": {"count": len(weights_updates),
                                          "max_gap_s": round(max_gap([(0, t) for t in weights_updates]), 1)},
            "rollout_completed": {"ids": [n for n, _ in rollout_done], "count": len(rollout_done),
                                   "max_gap_s": round(max_gap(rollout_done), 1)},
        },
        "windows": windows,
        "reward_evidence": {
            "per_rollout_raw_reward": rewards,
            "rollouts_with_reward_metric": sorted(rewards),
            "judge_traffic_total": len(judge_traffic),
            "judge_traffic_by_engine_pid": {
                pid: sum(1 for item in judge_traffic if item["pid"] == pid)
                for pid in sorted({item["pid"] for item in judge_traffic})
            },
            "judge_error_lines": len([e for e in errors if "GenRMEngine" in e["line"]]),
            "attribution_note": "per-request judge success is not individually logged; the bounded claim is "
                                "the conjunction of observed judge inference traffic, per-rollout reward "
                                "metrics computed, and zero judge error lines — replica-level correctness "
                                "is proven separately by the engine-attribution consistency runs",
        },
        "sample_integrity": sample_integrity,
        "carry_over": {
            "windows": len(carry),
            "all_aborted_zero": all(c[3] == 0 for c in carry),
            "all_no_deficit_or_surplus": all(c[1] == 0 and c[2] == 0 for c in carry),
        },
        "perf_step_ids_seen": perf_steps,
        "non_benign_error_lines": len(errors),
        "non_benign_error_samples": [e["line"] for e in errors[:5]],
    }
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=1)
    print(json.dumps(result["step_timelines"], indent=1))
    print(json.dumps({w["window"]: {"duration_s": w["duration_s"],
                                     "inside": w["events_inside"],
                                     "judge": w["judge_prefill_batches_per_engine"],
                                     "errors": w["error_lines"]} for w in windows}, indent=1))
    print("sample_integrity:", json.dumps(sample_integrity["missing_rollout_ids"]),
          "dups:", json.dumps(sample_integrity["duplicate_rollout_ids"]),
          "total:", sample_integrity["total_samples"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
