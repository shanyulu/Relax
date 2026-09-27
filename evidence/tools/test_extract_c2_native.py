# Copyright (c) 2026 Relax Authors. All Rights Reserved.

import importlib.util
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location("extract_c2_native", Path(__file__).with_name("extract_c2_native.py"))
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def record(step: int = 0) -> str:
    native = {"train/step": step, "train/loss": 1.5, "train/grad_norm": 2.0, "train/lr-pg_0": 0.001}
    perf = {"perf/train_time": 1.0, "perf/actor_train_tokens": 128}
    return f"\x1b[36mActor\x1b[0m step {step}: {native}\x1b[0m\nperf {step}: {perf}\n"


def test_native_metrics_are_extracted(tmp_path: Path) -> None:
    (tmp_path / "job.log").write_text(record())
    parsed = module.parse_arm(tmp_path, expected_steps=1)
    assert parsed["native_valid"]
    assert parsed["loss_series"] == [1.5]
    assert parsed["grad_norm_series"] == [2.0]
    assert parsed["learning_rate_series"] == [{"train/lr-pg_0": 0.001}]


@pytest.mark.parametrize(
    "data",
    [
        record() * 2,
        record(1),
        record().splitlines()[-1] + "\n",
        record().replace("1.5", "nan"),
        record().replace("'train/step': 0", "'train/step': 2"),
    ],
)
def test_missing_duplicate_or_invalid_evidence_is_rejected(tmp_path: Path, data: str) -> None:
    (tmp_path / "job.log").write_text(data)
    assert not module.parse_arm(tmp_path, expected_steps=1)["native_valid"]


def test_expected_count_is_enforced(tmp_path: Path) -> None:
    (tmp_path / "job.log").write_text(record())
    assert not module.parse_arm(tmp_path, expected_steps=48)["native_valid"]
