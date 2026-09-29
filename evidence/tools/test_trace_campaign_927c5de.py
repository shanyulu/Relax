#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""CPU-only guards for the 927c5de overlap campaign ordering and provenance."""

from __future__ import annotations

import json
import pathlib
import sys
from argparse import Namespace

import pytest


HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

import trace_campaign_927c5de as campaign  # noqa: E402


def seal(lock: dict) -> dict:
    lock["_self_sha256"] = campaign.canonical_hash(lock)
    return lock


def base_lock(stage="CALIBRATION") -> dict:
    lock = {
        "SCHEMA": "TRACE_OVERLAP_CAMPAIGN_927C5DE/v1",
        "STAGE": stage,
        "PRODUCT_SHA": "a" * 40,
        "RECIPE_SHA256": "b" * 64,
        "DATASET_SHA256": "c" * 64,
        "ENV_FINGERPRINT_SHA256": "d" * 64,
        "PROTOCOL_SHA256": "e" * 64,
        "ANALYZER_SHA256": "f" * 64,
        "RUNNER_SHA256": "2" * 64,
        "EXPECTED_STEPS": 48,
        "SAVE": "0",
        "CHECKPOINT_POLICY": "NONE_TRACES_ONLY",
        "TRACE_ARGS": campaign.TRACE_ARGS,
        "TRACE_DIR_TEMPLATE": "{out}/{arm}/train_trace",
        "TOPOLOGY": {"kind": "DP4", "gpus": 4},
        "ARM_ORDER": campaign.CALIBRATION_ARMS if stage == "CALIBRATION" else campaign.MEASUREMENT_ARMS,
        "RECIPE_ENV": {"SAVE": "0", "NUM_ROLLOUT": "48", "GLOBAL_BATCH_SIZE": "32"},
        "ON_PROFILE": campaign.ON_PROFILE,
    }
    if stage == "MEASUREMENT":
        lock["CALIBRATION_RESULT_SHA256"] = "3" * 64
        lock["CALIBRATION_RESULT_COMMIT"] = "4" * 40
    return lock


def test_calibration_lock_rejects_drifted_arm_order_and_save_policy():
    lock = base_lock()
    lock["ARM_ORDER"] = ["O-C1-off", "O-C2-off", "O-C3-off", "O-M1-on"]
    with pytest.raises(ValueError, match="arm order"):
        campaign.validate_lock(seal(lock))

    lock = base_lock()
    lock["SAVE"] = "1"
    with pytest.raises(ValueError, match="SAVE=0"):
        campaign.validate_lock(seal(lock))

    lock = base_lock()
    lock["TRACE_ARGS"] = campaign.TRACE_ARGS[:-1]
    with pytest.raises(ValueError, match="trace arguments"):
        campaign.validate_lock(seal(lock))

    lock = base_lock("MEASUREMENT")
    del lock["CALIBRATION_RESULT_SHA256"]
    with pytest.raises(ValueError, match="calibration result"):
        campaign.validate_lock(seal(lock))


def test_calibration_lock_must_not_reference_a_result():
    lock = base_lock()
    lock["CALIBRATION_RESULT_SHA256"] = "3" * 64
    with pytest.raises(ValueError, match="must not reference a result"):
        campaign.validate_lock(seal(lock))


def test_execute_refuses_without_allow_run(tmp_path):
    lock_path = tmp_path / "O_CALIBRATION_LOCK.json"
    lock_path.write_text(json.dumps(seal(base_lock())))
    args = Namespace(
        allow_run=False,
        lock=lock_path,
        arms="O-C1-off,O-C2-off,O-C3-off,O-C4-off",
        out=tmp_path / "campaign",
        product=tmp_path,
        dashboard="http://127.0.0.1:8265",
        gcs="127.0.0.1:6379",
        venv="/nonexistent",
        megatron="/nonexistent",
        bridge="/nonexistent",
    )
    with pytest.raises(ValueError, match="--allow-run"):
        campaign.cmd_execute(args)
    assert not (tmp_path / "campaign").exists()


def test_validate_arm_requires_four_rank_traces_and_identity(tmp_path):
    lock = seal(base_lock())
    lock_sha = "5" * 64
    arm = tmp_path / "O-C1-off"
    (arm / "train_trace").mkdir(parents=True)
    manifest = {
        "run_id": "O-C1-off",
        "lock_sha256": lock_sha,
        "product_sha": lock["PRODUCT_SHA"],
        "recipe_sha256": lock["RECIPE_SHA256"],
        "dataset_sha256": lock["DATASET_SHA256"],
        "env_fingerprint_sha256": lock["ENV_FINGERPRINT_SHA256"],
        "protocol_sha256": lock["PROTOCOL_SHA256"],
        "analyzer_sha256": lock["ANALYZER_SHA256"],
        "runner_sha256": lock["RUNNER_SHA256"],
        "expected_steps": 48,
        "job_status": "SUCCEEDED",
        "valid": True,
        "resources_returned": True,
        "driver_source_sha256_before": "source",
        "driver_source_sha256_after": "source",
        "worker_source_hashes": {"worker": "source"},
        "trace_summary": {"trace_files": 4, "rank_ids": [0, 1, 2, 3]},
    }
    (arm / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="four rank traces"):
        campaign.validate_arm(arm, lock, lock_sha)

    for rank in range(4):
        (arm / "train_trace" / f"rank{rank}.pt.trace.json.gz").write_bytes(b"gz")
    campaign.validate_arm(arm, lock, lock_sha)

    manifest["analyzer_sha256"] = "0" * 64
    (arm / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="analyzer_sha256 drift"):
        campaign.validate_arm(arm, lock, lock_sha)


def test_validate_execution_rejects_partial_or_reordered_arms(tmp_path):
    lock = seal(base_lock())
    lock_path = tmp_path / "O_CALIBRATION_LOCK.json"
    lock_path.write_text(json.dumps(lock))
    args = Namespace(product=tmp_path)
    with pytest.raises(ValueError, match="frozen stage order"):
        campaign._validate_execution(args, json.loads(json.dumps(lock)), ["O-C1-off", "O-C2-off"])
    with pytest.raises(ValueError, match="frozen stage order"):
        campaign._validate_execution(
            args, json.loads(json.dumps(lock)), ["O-C2-off", "O-C1-off", "O-C3-off", "O-C4-off"]
        )
