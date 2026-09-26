#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Summarise one real Relax run for the Task 11 acceptance evidence.

Usage:
    python analyze_run.py <job.log> <observer_evidence_dir> [--out summary.json]

Reads only files; never touches the cluster. Every number it prints is either
present in the raw log/JSONL or omitted alongside the reason it is missing --
the tool refuses to invent a value, because the whole point of the acceptance
protocol is that a reader can trace each figure back to an artefact.
"""

import argparse
import json
import pathlib
import re
import statistics
import sys
from typing import Any, Dict, List, Optional, Tuple

STEP_RE = re.compile(r"^step (\d+): \{(.*)\}\s*$", re.MULTILINE)
PAIR_RE = re.compile(r"'([^']+)':\s*([^,}]+)")
PERF_RE = re.compile(r"'perf/([a-z_/]+)':\s*([0-9.eE+-]+)")


def parse_steps(log_text: str) -> Dict[str, List[float]]:
    """Collect per-step numeric train metrics keyed by field name."""
    series: Dict[str, List[float]] = {}
    for _, body in STEP_RE.findall(log_text):
        for key, raw in PAIR_RE.findall(body):
            try:
                value = float(raw)
            except ValueError:
                continue
            series.setdefault(key, []).append(value)
    return series


def parse_perf(log_text: str) -> Dict[str, List[float]]:
    """Collect the perf/ metrics Relax already emits, in order of appearance."""
    series: Dict[str, List[float]] = {}
    for key, raw in PERF_RE.findall(log_text):
        try:
            series.setdefault(f"perf/{key}", []).append(float(raw))
        except ValueError:
            continue
    return series


def describe(values: List[float]) -> Optional[Dict[str, float]]:
    """Return p50/p95/p99/mean/min/max/n, or None when there is no sample."""
    if not values:
        return None
    ordered = sorted(values)
    count = len(ordered)

    def quantile(fraction: float) -> float:
        index = min(count - 1, max(0, int(round(fraction * (count - 1)))))
        return ordered[index]

    return {
        "n": count,
        "min": ordered[0],
        "p50": statistics.median(ordered),
        "p95": quantile(0.95),
        "p99": quantile(0.99),
        "mean": statistics.fmean(ordered),
        "max": ordered[-1],
    }


def read_jsonl(path: pathlib.Path) -> Tuple[List[dict], Dict[str, int]]:
    """Read JSONL, tolerating a torn final line.

    A SIGKILL during a large flush can leave the last line half-written. That
    line is skipped and counted as ``truncated_tail`` rather than making the
    whole run's evidence unreadable; any earlier malformed line is counted as
    ``malformed``. The write side deliberately does not fsync per batch, so this
    read-side tolerance is what keeps a killed run usable.
    """
    if not path.exists():
        return [], {"truncated_tail": 0, "malformed": 0}
    records: List[dict] = []
    counts = {"truncated_tail": 0, "malformed": 0}
    lines = path.read_text(errors="replace").splitlines()
    for index, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            if index == len(lines) - 1:
                counts["truncated_tail"] += 1
            else:
                counts["malformed"] += 1
    return records, counts


def read_json(path: pathlib.Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=pathlib.Path)
    parser.add_argument("evidence", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path, default=None)
    args = parser.parse_args()

    log_text = args.log.read_text(errors="replace") if args.log.exists() else ""
    summary: Dict[str, Any] = {
        "log": str(args.log),
        "evidence_dir": str(args.evidence),
        "log_present": args.log.exists(),
    }
    if not args.log.exists():
        summary["error"] = "job log missing"

    steps = parse_steps(log_text)
    perf = parse_perf(log_text)
    summary["train_metrics"] = {key: describe(values) for key, values in sorted(steps.items())}
    summary["perf_metrics"] = {key: describe(values) for key, values in sorted(perf.items())}
    summary["step_time"] = describe(perf.get("perf/step_time", []))

    envelopes, envelope_reads = read_jsonl(args.evidence / "straggler_envelopes.jsonl")
    verdicts, verdict_reads = read_jsonl(args.evidence / "straggler_verdicts.jsonl")
    collector_status = read_json(args.evidence / "collector_status.json")
    summary["observation"] = {
        "envelopes": len(envelopes),
        "verdicts": len(verdicts),
        "verdict_kinds": {},
        "stages_seen": sorted({record.get("name") for record in envelopes if record.get("name")}),
        "ranks_seen": sorted({record.get("rank") for record in envelopes if record.get("rank") is not None}),
        "collector_status": collector_status or "missing",
        # A killed run must still yield usable evidence: a torn final line is
        # skipped and counted here instead of failing the read.
        "envelope_reads": envelope_reads,
        "verdict_reads": verdict_reads,
    }
    kinds: Dict[str, int] = {}
    for verdict in verdicts:
        kind = str(verdict.get("kind", "unknown"))
        kinds[kind] = kinds.get(kind, 0) + 1
    summary["observation"]["verdict_kinds"] = kinds

    text = json.dumps(summary, indent=2, sort_keys=True, default=str)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())