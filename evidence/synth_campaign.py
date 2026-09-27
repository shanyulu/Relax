#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Synthetic campaign generator for analyze_c1 gate tests.

Builds minimal S<n>-off/S<n>-on arm directories (manifest.json, summary.json,
job.log with `perf <i>: {...}` lines) under a tmp root, with injectable defects.
Used by test_analyze_c1_gate.py and by the pre-fix counterexample capture.
"""

import json
import pathlib

COMMIT = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
COMMIT_ALT = "cafebabecafebabecafebabecafebabecafebabe"
DATASET = "44f9ddacd1e078d60d1a65d43dda76283b5ba68c6db7bbd54462126cd6a59428"
DATASET_ALT = "0000000000000000000000000000000000000000000000000000000000000000"
RECIPE = "scripts/training/sft/run-qwen3-0.6B-4xgpu-dp4-observer.sh"


def write_arm(
    root: pathlib.Path,
    name: str,
    *,
    n_steps: int = 48,
    step_ids=None,
    values=None,
    exit_code: int = 0,
    valid: bool = True,
    enable=None,
    commit: str = COMMIT,
    dataset: str = DATASET,
    recipe: str = RECIPE,
    expected_steps=None,
    collector_envelopes=None,
    metric_present: bool = True,
    started_at: str = "2026-09-26T10:00:00",
):
    """Write one arm directory. ``step_ids`` overrides the ID sequence (for
    duplicate/missing/misaligned defects); ``values`` overrides per-step values.

    ``commit``/``dataset``/``recipe`` accept ``None`` to model an arm whose
    manifest lacks the preregistered fingerprint fields entirely."""
    arm_dir = root / name
    arm_dir.mkdir(parents=True, exist_ok=True)
    role = "on" if name.endswith("-on") else "off"
    ids = step_ids if step_ids is not None else list(range(n_steps))
    vals = values if values is not None else [15.0 + (i % 7) * 0.01 for i in range(len(ids))]
    lines = []
    for i, sid in enumerate(ids):
        if not metric_present:
            lines.append(f"perf {sid}: {{'perf/actor_train_tokens': 4983}}")
        else:
            lines.append(f"perf {sid}: {{'perf/train_time': {vals[i]:.6f}, 'perf/actor_train_time': {vals[i]*0.9:.6f}}}")
    (arm_dir / "job.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

    git_block = {"commit": commit, "tree_label": f"CLEAN@{commit[:11]}"} if commit else {}
    manifest = {
        "arm": role,
        "exit_code": exit_code,
        "valid": valid,
        "invalid_reason": None if valid else "declared invalid by the runner",
        "git": git_block,
        "dataset_sha256": dataset,
        "recipe": recipe,
        "relax_env": ({"RELAX_STRAGGLER_ENABLE": enable} if enable is not None else {}),
        "started_at": started_at,
        "order": "A->B",
        "slot": "A" if role == "off" else "B",
        "wall_seconds": 900.0,
    }
    if expected_steps is not None:
        manifest["expected_steps"] = expected_steps
    (arm_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    observation = {}
    if role == "on":
        envelopes = collector_envelopes if collector_envelopes is not None else 2112
        observation["collector_status"] = {
            "envelopes": envelopes,
            "judged_packets": envelopes,
            "late_packets": 0,
            "duplicate_packets": 0,
            "invalid_packets": 0,
            "envelope_path": "run_x/straggler_envelopes.jsonl",
            "verdict_path": "run_x/straggler_verdicts.jsonl",
        }
    summary = {
        "observation": observation,
        "perf_metrics": {},
        "step_time": {"n": len(ids), "mean": 15.0, "p50": 15.0, "p95": 15.1, "p99": 15.2, "min": 15.0, "max": 15.2},
    }
    (arm_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return arm_dir


def on_values(off_base=15.0, n=48, factor=1.001):
    """ON-arm values at ``factor`` times a flat OFF base (pure overhead)."""
    return [off_base * factor] * n


def write_pair(root, session, *, n_steps=48, expected_steps=48, on_factor=1.001, **kwargs):
    """Write one well-formed OFF/ON pair unless per-arm kwargs override defects."""
    off_kwargs = {k[len("off_"):]: v for k, v in kwargs.items() if k.startswith("off_")}
    on_kwargs = {k[len("on_"):]: v for k, v in kwargs.items() if k.startswith("on_")}
    write_arm(
        root, f"S{session}-off", n_steps=n_steps, expected_steps=expected_steps,
        values=[15.0] * n_steps, started_at=f"2026-09-26T1{session % 10}:00:00", **off_kwargs
    )
    on_final = {"enable": "1"}
    on_final.update(on_kwargs)
    write_arm(
        root, f"S{session}-on", n_steps=n_steps, expected_steps=expected_steps,
        values=[15.0 * on_factor] * n_steps,
        started_at=f"2026-09-26T1{session % 10}:30:00", **on_final
    )
