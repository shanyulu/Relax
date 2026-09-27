# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Three-timeline re-analysis of the train-continuity r5 raw artifacts.

Answers the review finding that the driver merged steps+rollouts into one
stall bound and that `served > 0` cannot by itself prove the elastic replica
contributed successful rewards. Parses the RAW ray job driver log (not the
scraped two-line-per-event summary) plus the monitor's engine snapshots.
"""

import json
import re
import sys
from datetime import datetime

LOG = "/tmp/ray/session_2026-09-26_00-09-07_869909_951677/logs/job-driver-raysubmit_qT4vVNVyiMub3sur.log"
RES = "/root/autodl-tmp/relax-work/task4-pr/demos/task4_genrm/results/train_continuity_20260925_r5"

TS = re.compile(r"2026-09-26 (\d{2}:\d{2}:\d{2})")
BASE = datetime(2026, 9, 26)


def ts_of(line):
    m = TS.search(line)
    return (BASE.replace(hour=int(m.group(1)[:2]), minute=int(m.group(1)[3:5]), second=int(m.group(1)[6:]))
            - BASE).total_seconds() if m else None


def main():
    text = open(LOG, encoding="utf-8", errors="replace").read()
    lines = text.splitlines()

    steps, rollouts_done, saved_samples, carry, fully = [], [], [], [], []
    metric_rollouts = set()
    for line in lines:
        if "Actor training step" in line:
            n = int(re.search(r"Actor training step (\d+)", line).group(1))
            t = ts_of(line)
            if t is not None:
                steps.append((n, t))
        if "Rollout fully completed for rollout_id:" in line:
            n = int(re.search(r"rollout_id: (\d+)", line).group(1))
            t = ts_of(line)
            fully.append((n, t))
        if "Saved rollout result" in line:
            c = int(re.search(r"\((\d+) samples\)", line).group(1))
            saved_samples.append((c, ts_of(line)))
        if "carry-over: committed_current=" in line:
            carry.append(dict(zip(
                ["committed_current", "next_step_deficit", "oversample_surplus", "aborted"],
                [int(x) for x in re.findall(r"=(\d+)", line)])))
        m = re.search(r"rollout (\d+): \{", line)
        if m and "raw_reward" in line:
            metric_rollouts.add(int(m.group(1)))

    ev = json.load(open(f"{RES}/events.json"))
    so = next(e for e in ev if e["event"] == "scale_out_final")
    si = next(e for e in ev if e["event"] == "scale_in_final")
    esc = next(e for e in ev if e["event"] == "elastic_served_check")
    t0 = next(e for e in ev if e["event"] == "monitor_start")["t"]
    so_t, si_t = so["t"] - t0, si["t"] - t0

    def max_gap(seq):
        s = sorted(t for _, t in seq)
        return max((b - a for a, b in zip(s, s[1:])), default=0.0)

    ids_steps = [n for n, _ in steps]
    ids_fully = [n for n, _ in fully]
    samples_total = sum(c for c, _ in saved_samples)

    elastic_key = next(iter(esc["served"]))
    snaps = [e for e in ev if e["event"] == "engines_snapshot" and elastic_key in e.get("served", {})]
    elastic_series = [(e["t"] - t0, e["served"][elastic_key]) for e in snaps]
    in_window = [(t, s) for t, s in elastic_series if so_t <= t <= si_t]
    rose = in_window and (max(s for _, s in in_window) > 0)
    zero_abort = all(c["aborted"] == 0 for c in carry)
    no_deficit = all(c["next_step_deficit"] == 0 and c["oversample_surplus"] == 0 for c in carry)

    err_lines = [
        ln for ln in lines
        if re.search(r"\b(error|exception|traceback|failed)\b", ln, re.I)
        and not re.search(r"error_injection|failed to import flash_attn|Inferring the appropriate|failed for pad|failed to send|read timeout", ln, re.I)
    ]

    out = {
        "scale_window_s": [round(so_t, 1), round(si_t, 1)],
        "optimizer_steps": {
            "ids": ids_steps, "count": len(ids_steps),
            "max_gap_s": round(max_gap(steps), 1),
            "max_gap_spanning_scale_window": any(
                so_t <= a < si_t <= b for (n1, a), (n2, b) in zip(steps, steps[1:])),
        },
        "rollout_completions": {
            "ids_fully_completed": ids_fully, "count": len(ids_fully),
            "max_gap_s": round(max_gap(fully), 1),
        },
        "reward_returns": {
            "rollouts_with_raw_reward_metric": sorted(metric_rollouts),
            "saved_sample_counts": [c for c, _ in saved_samples],
            "samples_total": samples_total,
        },
        "carry_over": {"windows": len(carry), "all_aborted_zero": zero_abort, "no_deficit_or_surplus": no_deficit},
        "elastic_engine": {
            "key": elastic_key,
            "served_series_in_window": in_window[-3:],
            "served_rose_during_scaled_window": rose,
        },
        "log_error_lines_after_filter": len(err_lines),
        "samples_of_filtered_error_lines": [ln[:120] for ln in err_lines[:5]],
    }
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    sys.exit(main())
