# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Prevent observable file activity from becoming unsupported acceptance
claims."""

import gzip
import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))

import c3_summarize
import trace_overlap_metrics


def test_unrelated_log_anchor_is_not_latency(tmp_path, monkeypatch):
    events = tmp_path / "events.json"
    events.write_text(
        json.dumps(
            {
                "events": [
                    {"event": "log_line", "kind": "step", "mono": 1.0},
                    {"event": "verdict_visible", "mono": 1.6},
                ]
            }
        )
    )
    control = tmp_path / "control.json"
    control.write_text("{}")
    verdicts = tmp_path / "verdicts.jsonl"
    verdicts.write_text("")
    out = tmp_path / "summary.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "c3_summarize",
            "--events",
            str(events),
            "--control",
            str(control),
            "--verdicts",
            str(verdicts),
            "--out",
            str(out),
        ],
    )
    assert c3_summarize.main() == 0
    result = json.loads(out.read_text())
    assert result["unmatched_log_to_file_gap"]["p50_s"] == 0.6
    assert result["interval_anchor_to_verdict_persist"] == {"n": 0, "status": "UNMEASURED"}
    assert result["tail_window"]["status"] == "UNVERIFIED"


def test_nested_gpu_intervals_do_not_create_false_idle_gaps(tmp_path):
    path = tmp_path / "rank.trace.json.gz"
    with gzip.open(path, "wt") as stream:
        json.dump(
            {
                "traceEvents": [
                    {"cat": "kernel", "name": "compute", "ts": 0, "dur": 100},
                    {"cat": "kernel", "name": "nccl", "ts": 10, "dur": 10},
                    {"cat": "kernel", "name": "compute", "ts": 30, "dur": 10},
                ]
            },
            stream,
        )
    result = trace_overlap_metrics.classify(path)
    assert result["inter_kernel_gap_us"] == 0
    assert result["overlap_ratio"] == 1
    assert "only" in result["global_sync_count_scope"]
