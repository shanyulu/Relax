# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Exercise acceptance commands, not copies of their implementation."""

import gzip
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from c2_lock import validate_lock  # noqa: E402


def seal(lock):
    lock["_self_sha256"] = None
    lock["_self_sha256"] = hashlib.sha256(json.dumps(lock, sort_keys=True).encode()).hexdigest()
    return lock


def base_lock():
    return {
        "PRODUCT_SHA": "a" * 40,
        "DATASET_SHA256": "b" * 64,
        "RECIPE_SHA256": "c" * 64,
        "ENV_FINGERPRINT_SHA256": "d" * 64,
        "EXPECTED_STEPS": 48,
        "MEASUREMENT_N_PAIRS": 1,
        "ARM_ORDER": ["C2M1-off", "C2M1-on"],
        "TOLERANCES": {"mode": "EXACT_EQUALITY"},
    }


@pytest.mark.parametrize("n", [0, -1, True, 1.5])
def test_invalid_pair_count_is_not_pass(tmp_path, n):
    lock = base_lock()
    lock["MEASUREMENT_N_PAIRS"] = n
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(seal(lock)))
    out = tmp_path / "out.json"
    run = subprocess.run(
        [
            sys.executable,
            str(HERE / "c2_lock.py"),
            "compare",
            "--lock",
            str(path),
            "--calibration-result",
            str(tmp_path / "absent"),
            "--campaign",
            str(tmp_path),
            "--out",
            str(out),
        ],
        capture_output=True,
    )
    assert run.returncode == 2
    assert json.loads(out.read_text())["verdict"] == "INVALID"


def test_tampered_lock_rejected():
    lock = seal(base_lock())
    lock["TOLERANCES"]["loss_series"] = 1000
    with pytest.raises(ValueError, match="self hash"):
        validate_lock(lock)


@pytest.mark.parametrize(
    "scenario,expected,code",
    [
        ("complete", "PASS", 0),
        ("regression", "NOT_PASS", 1),
        ("missing-rank", "INVALID", 2),
        ("duplicate-rank", "INVALID", 2),
        ("wrong-hash", "INVALID", 2),
    ],
)
def test_trace_cli_checks_raw_coverage_and_exit_code(tmp_path, scenario, expected, code):
    hashes = {}
    for arm in ("TR0-off", "TR0-off2", "TR1-off", "TR1-on"):
        directory = tmp_path / arm / "train_trace"
        directory.mkdir(parents=True)
        count = 3 if scenario == "missing-rank" and arm == "TR1-on" else 4
        for rank in range(count + int(scenario == "duplicate-rank" and arm == "TR1-on")):
            path = directory / f"train_rank{rank % 4}_sample{rank}.pt.trace.json.gz"
            comm_start = 20 if scenario == "regression" and arm == "TR1-on" else 0
            with gzip.open(path, "wt") as stream:
                json.dump(
                    {
                        "traceEvents": [
                            {"cat": "kernel", "name": "compute", "ts": 0, "dur": 10},
                            {"cat": "kernel", "name": "nccl", "ts": comm_start, "dur": 10},
                        ]
                    },
                    stream,
                )
            hashes[str(path.relative_to(tmp_path))] = hashlib.sha256(path.read_bytes()).hexdigest()
    if scenario == "wrong-hash":
        hashes[next(iter(hashes))] = "0" * 64
    (tmp_path / "RAW_TRACE_SHA256.json").write_text(json.dumps(hashes))
    out = tmp_path / "verdict.json"
    run = subprocess.run(
        [sys.executable, str(HERE / "trace_verdict.py"), "--base", str(tmp_path), "--out", str(out)],
        capture_output=True,
    )
    assert run.returncode == code, run.stderr
    assert json.loads(out.read_text())["verdict"] == expected
