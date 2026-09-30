# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""CPU-only regression tests for the Task 11 native loss campaign gates."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from pytest import approx


TOOL = Path(__file__).with_name("native_loss_campaign_927c5de.py")
sys.path.insert(0, str(TOOL.parent))
SPEC = importlib.util.spec_from_file_location("native_loss_campaign_927c5de", TOOL)
assert SPEC and SPEC.loader
campaign = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = campaign
SPEC.loader.exec_module(campaign)


def test_calibration_uses_all_six_off_pairs_and_doubles_maximum() -> None:
    lock = {"_self_sha256": "lock", "arm_order": campaign.CALIBRATION_ARMS}
    arms = {
        name: {
            "manifest_sha256": name,
            "loss_series": [float(i) + offset for i in range(campaign.STEPS)],
            "grad_norm_series": [float(i) + offset * 2 for i in range(campaign.STEPS)],
        }
        for name, offset in zip(campaign.CALIBRATION_ARMS, [0.0, 0.1, 0.3, 0.2])
    }
    result = campaign.calibration_result(lock, arms)
    assert len(result["contrasts"]) == 6
    assert result["tolerances"]["loss_series"] == approx(0.6)
    assert result["tolerances"]["grad_norm_series"] == approx(1.2)
    assert result["_self_sha256"] == campaign.canonical_sha(result)


def test_calibration_rejects_missing_or_reordered_off_arms() -> None:
    lock = {"_self_sha256": "lock", "arm_order": campaign.CALIBRATION_ARMS}
    with pytest.raises(ValueError, match="complete and in frozen order"):
        campaign.calibration_result(lock, {})
    with pytest.raises(ValueError, match="complete and in frozen order"):
        campaign.calibration_result(lock, dict.fromkeys(reversed(campaign.CALIBRATION_ARMS), {}))


def test_resolved_argv_requires_seed_and_rejects_all_save_flags() -> None:
    assert campaign.validate_resolved_argv(b"--seed\x001234\x00--foo\x00bar\x00") == ["--seed", "1234", "--foo", "bar"]


@pytest.mark.parametrize("flag", ["--save", "--save-interval"])
def test_resolved_argv_rejects_checkpoint_flags(flag: str) -> None:
    with pytest.raises(ValueError, match="SAVE=0"):
        campaign.validate_resolved_argv(f"--seed\x00{campaign.SEED}\x00{flag}\x001\x00".encode())


def test_resolved_argv_rejects_wrong_seed() -> None:
    with pytest.raises(ValueError, match="frozen seed"):
        campaign.validate_resolved_argv(b"--seed\x000001\x00")


def test_compare_pair_distinguishes_invalid_pair_from_valid_threshold_failure() -> None:
    baseline = {
        "native_step_ids": list(range(campaign.STEPS)),
        "token_series": [32] * campaign.STEPS,
        "learning_rate_series": [{"lr": 1e-5}] * campaign.STEPS,
        "update_count": campaign.STEPS,
        "resolved_argv_sha256": "same",
        "loss_series": [0.0] * campaign.STEPS,
        "grad_norm_series": [0.0] * campaign.STEPS,
    }
    shifted = {**baseline, "loss_series": [0.5] * campaign.STEPS}
    tolerance = {"loss_series": 0.5, "grad_norm_series": 0.0}
    assert campaign.compare_pair(baseline, shifted, tolerance)["status"] == "PASS"
    too_far = {**baseline, "loss_series": [0.5001] * campaign.STEPS}
    assert campaign.compare_pair(baseline, too_far, tolerance)["status"] == "NOT_PASS"
    wrong_tokens = {**shifted, "token_series": [31] * campaign.STEPS}
    assert campaign.compare_pair(baseline, wrong_tokens, tolerance)["status"] == "INVALID"


def test_resolved_argv_and_verdict_hashes_detect_tampering() -> None:
    value = {"status": "PASS", "_self_sha256": None}
    value["_self_sha256"] = campaign.canonical_sha(value)
    assert value["_self_sha256"] == campaign.canonical_sha(value)
    value["status"] = "NOT_PASS"
    assert value["_self_sha256"] != campaign.canonical_sha(value)
