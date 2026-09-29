#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Classify the 927c5de C3 arms under the frozen protocol rules.

Reads each arm's retained straggler JSONL and applies the preregistered
classification from ``C3_EVENT_CHAIN_PROTOCOL_927C5DE.md``:

- healthy arm: every straggler verdict is a false positive (count + detail);
- slow arm (injection on rank 3): rank-3 stragglers are target detections;
  any other rank is an *explained secondary effect* only if its slow windows
  temporally overlap the target's stall windows AND its workload stayed
  comparable, otherwise a false positive.

Also records the tail-window observables (last verdict window, the job log's
final collector report and process-close lines). No latency is computed: the
protocol reports stage-level localization and rollout-level platform
confirmation only; per-event latency stays UNMEASURED.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


TARGET_RANK = 3


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verdict_files(arm_dir: Path) -> list[Path]:
    return sorted((arm_dir / "straggler").rglob("straggler_verdicts.jsonl"))


def load_verdicts(arm_dir: Path) -> list[dict[str, Any]]:
    files = verdict_files(arm_dir)
    if len(files) != 1:
        raise RuntimeError(
            f"INCOMPLETE: expected exactly one verdict file under {arm_dir}/straggler, found {len(files)}"
        )
    verdicts = []
    for line in files[0].read_text().strip().splitlines():
        if line:
            verdicts.append(json.loads(line))
    return verdicts


def _detail(verdict: dict[str, Any]) -> dict[str, Any]:
    facts = verdict.get("facts", {})
    return {
        "rank": verdict.get("rank"),
        "stage": verdict.get("name"),
        "window_index": verdict.get("window_index"),
        "deviation": verdict.get("deviation"),
        "consecutive_windows": verdict.get("consecutive_windows"),
        "reason": verdict.get("reason"),
        "workload_evidence_degraded": facts.get("workload_evidence_degraded"),
    }


def classify_healthy(verdicts: list[dict[str, Any]]) -> dict[str, Any]:
    stragglers = [v for v in verdicts if v.get("kind") == "straggler"]
    return {
        "total_verdicts": len(verdicts),
        "straggler_verdicts": len(stragglers),
        "false_positives": len(stragglers),
        "false_positive_details": [_detail(v) for v in stragglers],
        "uncertain": sum(1 for v in verdicts if v.get("kind") == "uncertain"),
        "recovered": sum(1 for v in verdicts if v.get("kind") == "recovered"),
    }


def classify_slow(verdicts: list[dict[str, Any]]) -> dict[str, Any]:
    stragglers = [v for v in verdicts if v.get("kind") == "straggler"]
    target = [v for v in stragglers if v.get("rank") == TARGET_RANK]
    target_windows = {v.get("window_index") for v in target}
    non_target = []
    for verdict in (v for v in stragglers if v.get("rank") != TARGET_RANK):
        facts = verdict.get("facts", {})
        degraded = facts.get("workload_evidence_degraded")
        window = verdict.get("window_index")
        overlaps = any(abs(window - tw) <= 1 for tw in target_windows) if window is not None else False
        non_target.append(
            {
                **_detail(verdict),
                "overlaps_target_windows": overlaps,
                "classification": "explained_secondary_effect"
                if (overlaps and degraded is False)
                else "false_positive",
            }
        )
    return {
        "total_verdicts": len(verdicts),
        "straggler_verdicts": len(stragglers),
        "target_rank": TARGET_RANK,
        "target_detections": len(target),
        "target_details": [_detail(v) for v in target],
        "target_max_deviation": max((v.get("deviation") or 0.0 for v in target), default=None),
        "non_target_alarms": non_target,
        "uncertain": sum(1 for v in verdicts if v.get("kind") == "uncertain"),
        "recovered": sum(1 for v in verdicts if v.get("kind") == "recovered"),
    }


def tail_record(arm_dir: Path) -> dict[str, Any]:
    job_log = arm_dir / "job.log"
    text = job_log.read_text(errors="replace") if job_log.is_file() else ""
    reports = [line for line in text.splitlines() if "straggler[" in line and "envelopes=" in line]
    shutdown = [line for line in text.splitlines() if "Ray shutdown successfully" in line]
    return {
        "final_collector_report_lines": reports[-3:] if reports else [],
        "process_close_record": shutdown[-1:] if shutdown else [],
        "job_log_sha256": sha256_file(job_log) if job_log.is_file() else None,
    }


def analyse(healthy_dir: Path, slow_dir: Path, lock_path: Path) -> dict[str, Any]:
    return {
        "schema": "C3_927C5DE_RESULT/v1",
        "lock_sha256": sha256_file(lock_path),
        "healthy_manifest_sha256": sha256_file(healthy_dir / "manifest.json"),
        "slow_manifest_sha256": sha256_file(slow_dir / "manifest.json"),
        "healthy": classify_healthy(load_verdicts(healthy_dir)),
        "slow": classify_slow(load_verdicts(slow_dir)),
        "healthy_tail": tail_record(healthy_dir),
        "slow_tail": tail_record(slow_dir),
        "latency_claim": "UNMEASURED — stage-level localization and rollout-level platform confirmation only (protocol section 1)",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--healthy", type=Path, required=True)
    parser.add_argument("--slow", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        print("INVALID: refusing to overwrite result", file=sys.stderr)
        return 2
    try:
        result = analyse(args.healthy, args.slow, args.lock)
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"INCOMPLETE: {exc}", file=sys.stderr)
        return 1
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    summary = {
        "healthy_false_positives": result["healthy"]["false_positives"],
        "slow_target_detections": result["slow"]["target_detections"],
        "slow_non_target": len(result["slow"]["non_target_alarms"]),
    }
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
