#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Frozen-rule classification tests for the 927c5de C3 analyzer."""

from __future__ import annotations

import json
import pathlib
import sys

import pytest


HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

import c3_analyze_927c5de as analyzer  # noqa: E402


def verdict(kind, rank, window, deviation=0.2, stage="forward-compute", degraded=False):
    return {
        "kind": kind,
        "name": stage,
        "rank": rank,
        "window_index": window,
        "deviation": deviation,
        "consecutive_windows": 3 if kind == "straggler" else 0,
        "reason": "gpu_stream_stall" if kind == "straggler" else "below_absolute_floor",
        "facts": {"workload_evidence_degraded": degraded},
    }


def arm(tmp_path: pathlib.Path, name: str, verdicts: list[dict]) -> pathlib.Path:
    arm_dir = tmp_path / name
    run_dir = arm_dir / "straggler" / "run_abc"
    run_dir.mkdir(parents=True)
    (run_dir / "straggler_verdicts.jsonl").write_text("\n".join(json.dumps(v) for v in verdicts) + "\n")
    (arm_dir / "manifest.json").write_text("{}")
    (arm_dir / "job.log").write_text(
        "2026-09-29 straggler[rank0]: envelopes=10 judged=10\n... Ray shutdown successfully\n"
    )
    return arm_dir


def test_healthy_stragglers_are_false_positives(tmp_path):
    healthy = arm(
        tmp_path,
        "healthy",
        [verdict("straggler", 1, 12), verdict("uncertain", 0, 9), verdict("recovered", 2, 15)],
    )
    slow = arm(tmp_path, "slow", [verdict("straggler", 3, 20)])
    lock = tmp_path / "C3_LOCK.json"
    lock.write_text("{}")
    result = analyzer.analyse(healthy, slow, lock)
    assert result["healthy"]["false_positives"] == 1
    assert result["healthy"]["false_positive_details"][0]["rank"] == 1
    assert result["healthy"]["uncertain"] == 1
    assert result["healthy"]["recovered"] == 1


def test_non_target_classification_follows_the_frozen_rule(tmp_path):
    healthy = arm(tmp_path, "healthy", [])
    # rank 2 fires in a window adjacent to a rank-3 stall window with comparable
    # workload -> explained secondary effect; rank 1 fires far away -> false
    # positive; rank 0 fires adjacent but with degraded workload -> false
    # positive.
    slow = arm(
        tmp_path,
        "slow",
        [
            verdict("straggler", 3, 20),
            verdict("straggler", 3, 21),
            verdict("straggler", 2, 21, degraded=False),
            verdict("straggler", 1, 40, degraded=False),
            verdict("straggler", 0, 20, degraded=True),
            verdict("uncertain", 3, 25),
        ],
    )
    lock = tmp_path / "C3_LOCK.json"
    lock.write_text("{}")
    result = analyzer.analyse(healthy, slow, lock)
    slow_result = result["slow"]
    assert slow_result["target_detections"] == 2
    assert slow_result["target_max_deviation"] == 0.2
    by_rank = {row["rank"]: row for row in slow_result["non_target_alarms"]}
    assert by_rank[2]["classification"] == "explained_secondary_effect"
    assert by_rank[1]["classification"] == "false_positive"
    assert by_rank[0]["classification"] == "false_positive"
    assert result["latency_claim"].startswith("UNMEASURED")


def test_missing_or_ambiguous_verdict_files_fail_closed(tmp_path):
    healthy = arm(tmp_path, "healthy", [])
    slow = tmp_path / "slow"
    (slow / "straggler").mkdir(parents=True)
    (slow / "manifest.json").write_text("{}")
    (slow / "job.log").write_text("x\n")
    lock = tmp_path / "C3_LOCK.json"
    lock.write_text("{}")
    with pytest.raises(RuntimeError, match="INCOMPLETE"):
        analyzer.analyse(healthy, slow, lock)
