#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Tests for the generic, lock-before-see 927c5de C2 overlap verifier."""

import gzip
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, Sequence


HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import trace_verdict_927c5de as verdict  # noqa: E402


def write_trace(path: Path, ratio: float) -> None:
    """Write a minimal valid trace with compute=100us and controlled
    overlap."""
    path.parent.mkdir(parents=True, exist_ok=True)
    events = {
        "traceEvents": [
            {"cat": "kernel", "name": "compute", "ts": 0, "dur": 100},
            {"cat": "kernel", "name": "ncclKernel", "ts": 100 * (1 - ratio), "dur": 100},
            {"cat": "cuda_runtime", "name": "cudaDeviceSynchronize", "ts": 1, "dur": 1},
        ]
    }
    with gzip.open(path, "wt") as handle:
        json.dump(events, handle)


def add_arm(root: Path, name: str, ratio: float, *, ranks=(0, 1, 2, 3)) -> None:
    for rank in ranks:
        write_trace(root / name / "train_trace" / f"trace_rank{rank}_worker.pt.trace.json.gz", ratio)


def ledger(root: Path, arm_names: Sequence[str]) -> Dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for arm_name in arm_names
        for path in sorted((root / arm_name).rglob("*.pt.trace.json.gz"))
    }


def write_json(path: Path, value: Dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def calibration_config(root: Path, *, arm_names=("alpha", "bravo", "charlie", "delta")) -> Dict:
    return {
        "schema": verdict.SCHEMA,
        "phase": "calibration",
        "product_sha": "a" * 40,
        "expected_ranks": [0, 1, 2, 3],
        "arms": [{"id": name, "path": name, "condition": "OFF"} for name in arm_names],
        "contrasts": [
            {"name": "calibration-ab", "left": arm_names[0], "right": arm_names[1]},
            {"name": "calibration-ba", "left": arm_names[2], "right": arm_names[3]},
        ],
        "raw_trace_hashes": ledger(root, arm_names),
    }


def measurement_config(root: Path, calibration_path: Path) -> Dict:
    return {
        "schema": verdict.SCHEMA,
        "phase": "measurement",
        "product_sha": "a" * 40,
        "expected_ranks": [0, 1, 2, 3],
        "calibration_result_sha256": hashlib.sha256(calibration_path.read_bytes()).hexdigest(),
        "arms": [
            {"id": "m-ab-off", "path": "m-ab-off", "condition": "OFF"},
            {"id": "m-ab-on", "path": "m-ab-on", "condition": "ON"},
            {"id": "m-ba-off", "path": "m-ba-off", "condition": "OFF"},
            {"id": "m-ba-on", "path": "m-ba-on", "condition": "ON"},
        ],
        "pairs": [
            {"name": "measurement-ab", "off": "m-ab-off", "on": "m-ab-on", "order": "AB"},
            {"name": "measurement-ba", "off": "m-ba-off", "on": "m-ba-on", "order": "BA"},
        ],
        "raw_trace_hashes": ledger(root, ("m-ab-off", "m-ab-on", "m-ba-off", "m-ba-on")),
    }


def freeze(root: Path) -> Path:
    for name, ratio in (("alpha", 0.50), ("bravo", 0.52), ("charlie", 0.49), ("delta", 0.51)):
        add_arm(root, name, ratio)
    config = root / "calibration.json"
    output = root / "calibration_result.json"
    write_json(config, calibration_config(root))
    assert verdict.freeze(config, root, output) == 0
    return output


def test_generic_arm_descriptors_replace_hardcoded_legacy_layout(tmp_path):
    calibration = freeze(tmp_path)
    for name, ratio in (("m-ab-off", 0.50), ("m-ab-on", 0.49), ("m-ba-off", 0.51), ("m-ba-on", 0.50)):
        add_arm(tmp_path, name, ratio)
    config = tmp_path / "measurement.json"
    output = tmp_path / "measurement_result.json"
    write_json(config, measurement_config(tmp_path, calibration))
    assert verdict.compare(config, calibration, tmp_path, output) == 0
    result = json.loads(output.read_text())
    assert result["verdict"] == "PASS"
    assert {pair["order"] for pair in result["pairs"]} == {"AB", "BA"}
    assert result["self_sha256"] == verdict.canonical_sha256(
        {key: value for key, value in result.items() if key != "self_sha256"}
    )


def test_measurement_rejects_calibration_envelope_breach(tmp_path):
    calibration = freeze(tmp_path)
    for name, ratio in (("m-ab-off", 0.50), ("m-ab-on", 0.40), ("m-ba-off", 0.51), ("m-ba-on", 0.51)):
        add_arm(tmp_path, name, ratio)
    config = tmp_path / "measurement.json"
    output = tmp_path / "measurement_result.json"
    write_json(config, measurement_config(tmp_path, calibration))
    assert verdict.compare(config, calibration, tmp_path, output) == 1
    assert json.loads(output.read_text())["verdict"] == "NOT_PASS"


def test_missing_trace_is_incomplete(tmp_path):
    add_arm(tmp_path, "alpha", 0.5)
    add_arm(tmp_path, "bravo", 0.5)
    add_arm(tmp_path, "charlie", 0.5)
    config = tmp_path / "calibration.json"
    output = tmp_path / "calibration_result.json"
    write_json(config, calibration_config(tmp_path))
    assert verdict.freeze(config, tmp_path, output) == 1
    assert json.loads(output.read_text())["verdict"] == "INCOMPLETE"


def test_duplicate_rank_is_invalid(tmp_path):
    for name in ("alpha", "bravo", "charlie", "delta"):
        add_arm(tmp_path, name, 0.5)
    trace_dir = tmp_path / "alpha" / "train_trace"
    write_trace(trace_dir / "trace_rank0_copy.pt.trace.json.gz", 0.5)
    config = tmp_path / "calibration.json"
    output = tmp_path / "calibration_result.json"
    write_json(config, calibration_config(tmp_path))
    assert verdict.freeze(config, tmp_path, output) == 2
    assert json.loads(output.read_text())["verdict"] == "INVALID"


def test_hash_ledger_drift_is_invalid(tmp_path):
    for name in ("alpha", "bravo", "charlie", "delta"):
        add_arm(tmp_path, name, 0.5)
    config = calibration_config(tmp_path)
    first_key = next(iter(config["raw_trace_hashes"]))
    config["raw_trace_hashes"][first_key] = "0" * 64
    config_path = tmp_path / "calibration.json"
    output = tmp_path / "calibration_result.json"
    write_json(config_path, config)
    assert verdict.freeze(config_path, tmp_path, output) == 2
    assert json.loads(output.read_text())["verdict"] == "INVALID"


def test_measurement_rejects_product_drift(tmp_path):
    calibration = freeze(tmp_path)
    for name in ("m-ab-off", "m-ab-on", "m-ba-off", "m-ba-on"):
        add_arm(tmp_path, name, 0.5)
    config = measurement_config(tmp_path, calibration)
    config["product_sha"] = "b" * 40
    config_path = tmp_path / "measurement.json"
    output = tmp_path / "measurement_result.json"
    write_json(config_path, config)
    assert verdict.compare(config_path, calibration, tmp_path, output) == 2
    assert json.loads(output.read_text())["verdict"] == "INVALID"


def test_non_overwrite_is_rejected(tmp_path):
    calibration = freeze(tmp_path)
    assert verdict.freeze(tmp_path / "calibration.json", tmp_path, calibration) == 2
    assert json.loads(calibration.read_text())["verdict"] == "PASS"
