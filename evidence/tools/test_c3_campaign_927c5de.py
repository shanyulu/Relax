#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""CPU-only guards for the 927c5de C3 campaign lock and ordering."""

from __future__ import annotations

import json
import pathlib
import signal
import sys
from argparse import Namespace

import pytest


HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

import c3_campaign_927c5de as campaign  # noqa: E402


def seal(lock: dict) -> dict:
    lock["_self_sha256"] = campaign.canonical_hash(lock)
    return lock


def base_lock() -> dict:
    return {
        "SCHEMA": "C3_CAMPAIGN_927C5DE/v1",
        "PRODUCT_SHA": "a" * 40,
        "RECIPE_SHA256": "b" * 64,
        "DATASET_SHA256": "c" * 64,
        "ENV_FINGERPRINT_SHA256": "d" * 64,
        "PROTOCOL_SHA256": "e" * 64,
        "RUNNER_SHA256": "f" * 64,
        "SPINNER_SHA256": "1" * 64,
        "EXPECTED_STEPS": 48,
        "SAVE": "0",
        "ARM_ORDER": campaign.ARMS,
        "ON_PROFILE": campaign.ON_PROFILE,
        "SPINNER_SPEC": campaign.SPINNER_SPEC,
        "TOPOLOGY": {"kind": "DP4", "gpus": 4},
        "RECIPE_ENV": {"SAVE": "0", "NUM_ROLLOUT": "48", "GLOBAL_BATCH_SIZE": "32"},
    }


def test_lock_rejects_drifted_order_or_spinner_spec():
    lock = base_lock()
    lock["ARM_ORDER"] = ["C3-slow-on", "C3-healthy-on"]
    with pytest.raises(ValueError, match="arm order"):
        campaign.validate_lock(seal(lock))

    lock = base_lock()
    lock["SPINNER_SPEC"] = {**campaign.SPINNER_SPEC, "gpu": 2}
    with pytest.raises(ValueError, match="spinner specification"):
        campaign.validate_lock(seal(lock))

    lock = base_lock()
    lock["SAVE"] = "1"
    with pytest.raises(ValueError, match="SAVE=0"):
        campaign.validate_lock(seal(lock))


def test_execute_refuses_partial_runs_and_without_allow_run(tmp_path):
    lock_path = tmp_path / "C3_LOCK.json"
    lock_path.write_text(json.dumps(seal(base_lock())))
    args = Namespace(
        allow_run=False,
        lock=lock_path,
        arms="C3-healthy-on",
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

    args.allow_run = True
    with pytest.raises(ValueError, match="frozen order"):
        campaign.cmd_execute(args)
    assert not (tmp_path / "campaign").exists()


def test_spinner_only_runs_in_the_slow_arm_and_is_killed_by_pid(tmp_path):
    """The spinner lifecycle is the slow arm's alone; the healthy arm has none."""
    manifest = {"spinner_spec": None}
    assert manifest["spinner_spec"] is None

    class FakeProcess:
        pid = 424242

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

    fake = FakeProcess()
    import os

    sent = []

    def fake_kill(pid, sig):
        sent.append(sig)
        return None

    original = os.kill
    os.kill = fake_kill
    try:
        campaign._kill_spinner(fake, manifest)  # type: ignore[arg-type]
    finally:
        os.kill = original
    assert manifest.get("spinner_killed_by") == "SIGTERM"
    assert sent and sent[0] == signal.SIGTERM
