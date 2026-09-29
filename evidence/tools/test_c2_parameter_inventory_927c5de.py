#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""CPU-only retained-checkpoint export and calibration-builder tests."""

from __future__ import annotations

import pathlib
import sys

import pytest
import torch


HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

import c2_parameter_calibration_927c5de as builder  # noqa: E402
import c2_parameter_inventory_927c5de as inventory  # noqa: E402
import c2_parameter_verdict_927c5de as verdict  # noqa: E402


def identity():
    return {
        "PRODUCT_SHA": "a" * 40,
        "RECIPE_SHA256": "b" * 64,
        "DATASET_SHA256": "c" * 64,
        "ENV_FINGERPRINT_SHA256": "d" * 64,
        "PROTOCOL_SHA256": "e" * 64,
        "COMPARATOR_SHA256": "f" * 64,
        "LOCK_SHA256": "1" * 64,
        "EXPECTED_STEPS": 48,
    }


def checkpoint(path: pathlib.Path, value: float):
    path.mkdir()
    torch.save(
        {"weight": torch.tensor([value, 2.0], dtype=torch.bfloat16), "counter": torch.tensor([3], dtype=torch.int64)},
        path / "model.pt",
    )


def export(tmp_path, arm, value):
    source = tmp_path / f"{arm}-checkpoint"
    checkpoint(source, value)
    out = tmp_path / f"{arm}.json"
    result = inventory.export_inventory(source, out, identity=identity(), arm_name=arm)
    assert result["tensors"][0]["dtype"] == "int64" or any(item["dtype"] == "bfloat16" for item in result["tensors"])
    read = verdict.read_inventory(
        out, product_sha=identity()["PRODUCT_SHA"], protocol_sha256=identity()["PROTOCOL_SHA256"]
    )
    assert read["model.pt::weight"].dtype == "bfloat16"
    return out


def test_bfloat16_export_is_consumable_and_calibrates_fixed_contrasts(tmp_path):
    paths = {
        "P-C1-off": export(tmp_path, "P-C1-off", 1.0),
        "P-C2-off": export(tmp_path, "P-C2-off", 1.125),
        "P-C3-off": export(tmp_path, "P-C3-off", 1.0),
        "P-C4-off": export(tmp_path, "P-C4-off", 1.25),
    }
    loaded = {name: {"path": path, **builder.load_inventory(path, identity(), name)} for name, path in paths.items()}
    result = builder.build_calibration(loaded, identity())
    assert result["status"] == "FROZEN_OFF_ONLY"
    assert result["tensor_tolerances"]["model.pt::weight"] == pytest.approx(0.5)
    assert result["self_sha256"] == verdict.canonical_sha256(result)


def test_dcp_layout_fails_closed_before_any_comparison(tmp_path):
    checkpoint_dir = tmp_path / "dcp"
    checkpoint_dir.mkdir()
    (checkpoint_dir / "__0_0.distcp").write_bytes(b"not parsed")
    with pytest.raises(RuntimeError, match="DCP/sharded checkpoint"):
        inventory.export_inventory(
            checkpoint_dir, tmp_path / "inventory.json", identity=identity(), arm_name="P-C1-off"
        )
