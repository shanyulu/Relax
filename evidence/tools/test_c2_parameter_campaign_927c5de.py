#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""CPU-only guards for 927c5de C2 campaign ordering and provenance."""

from __future__ import annotations

import hashlib
import importlib.machinery
import json
import pathlib
import subprocess
import sys
import types
from argparse import Namespace

import pytest
import torch
from torch.distributed.checkpoint import FileSystemWriter
from torch.distributed.checkpoint.state_dict_saver import save as dcp_save


HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

import c2_parameter_campaign_927c5de as campaign  # noqa: E402
import c2_parameter_dcp_adapter_927c5de as adapter  # noqa: E402
import c2_parameter_inventory_927c5de as inventory  # noqa: E402
import c2_parameter_verdict_927c5de as verdict  # noqa: E402


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seal(lock: dict) -> dict:
    lock["_self_sha256"] = campaign.canonical_hash(lock)
    return lock


def base_lock(stage="CALIBRATION") -> dict:
    return {
        "SCHEMA": "C2_PARAMETER_CAMPAIGN_927C5DE/v1",
        "STAGE": stage,
        "PRODUCT_SHA": "a" * 40,
        "RECIPE_SHA256": "b" * 64,
        "DATASET_SHA256": "c" * 64,
        "ENV_FINGERPRINT_SHA256": "d" * 64,
        "PROTOCOL_SHA256": "e" * 64,
        "RUNNER_SHA256": "f" * 64,
        "COMPARATOR_SHA256": "1" * 64,
        "EXPECTED_STEPS": 48,
        "SAVE": 1,
        "CHECKPOINT_POLICY": "RETAIN_UNTIL_ARCHIVED",
        "TOPOLOGY": {"kind": "DP4", "gpus": 4},
        "ARM_ORDER": campaign.CALIBRATION_ARMS if stage == "CALIBRATION" else campaign.MEASUREMENT_ARMS,
        "RECIPE_ENV": {"SAVE": "1", "NUM_ROLLOUT": "48", "GLOBAL_BATCH_SIZE": "32"},
        "ON_PROFILE": campaign.ON_PROFILE,
    }


def test_calibration_lock_rejects_an_on_arm_and_measurement_needs_committed_result():
    lock = base_lock()
    lock["ARM_ORDER"] = ["P-C1-off", "P-C2-off", "P-C3-off", "P-M1-on"]
    with pytest.raises(ValueError, match="arm order"):
        campaign.validate_lock(seal(lock))
    lock = base_lock("MEASUREMENT")
    with pytest.raises(ValueError, match="calibration result"):
        campaign.validate_lock(seal(lock))


def test_validate_arm_rejects_missing_checkpoint_and_identity_drift(tmp_path):
    lock = seal(base_lock())
    lock_sha = "9" * 64
    arm = tmp_path / "P-C1-off"
    arm.mkdir()
    manifest = {
        "run_id": "P-C1-off",
        "lock_sha256": lock_sha,
        "product_sha": lock["PRODUCT_SHA"],
        "recipe_sha256": lock["RECIPE_SHA256"],
        "dataset_sha256": lock["DATASET_SHA256"],
        "env_fingerprint_sha256": lock["ENV_FINGERPRINT_SHA256"],
        "protocol_sha256": lock["PROTOCOL_SHA256"],
        "runner_sha256": lock["RUNNER_SHA256"],
        "comparator_sha256": lock["COMPARATOR_SHA256"],
        "expected_steps": 48,
        "job_status": "SUCCEEDED",
        "valid": True,
        "resources_returned": True,
        "driver_source_sha256_before": "source",
        "driver_source_sha256_after": "source",
        "worker_source_hashes": {"worker": "source"},
    }
    (arm / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="retained checkpoint missing"):
        campaign.validate_arm(arm, lock, lock_sha)
    checkpoint = arm / "checkpoints"
    checkpoint.mkdir()
    (checkpoint / "final.pt").write_bytes(b"retained")
    manifest["dataset_sha256"] = "0" * 64
    (arm / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="dataset_sha256 drift"):
        campaign.validate_arm(arm, lock, lock_sha)


def test_measurement_lock_requires_exact_committed_calibration(tmp_path):
    product = tmp_path / "product"
    product.mkdir()
    subprocess.run(["git", "init", "-q", str(product)], check=True)
    subprocess.run(["git", "-C", str(product), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(product), "config", "user.name", "Test"], check=True)
    (product / "README").write_text("x")
    subprocess.run(["git", "-C", str(product), "add", "README"], check=True)
    subprocess.run(["git", "-C", str(product), "commit", "-qm", "init"], check=True)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    subprocess.run(["git", "init", "-q", str(evidence)], check=True)
    subprocess.run(["git", "-C", str(evidence), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(evidence), "config", "user.name", "Test"], check=True)
    recipe, dataset, environment, protocol = (
        tmp_path / "recipe",
        tmp_path / "dataset",
        tmp_path / "env",
        tmp_path / "protocol",
    )
    for path in (recipe, dataset, environment, protocol):
        path.write_text(path.name)
    head = campaign.git(product, "rev-parse", "HEAD")
    calibration = {
        "status": "FROZEN_OFF_ONLY",
        "product_sha": head,
        "protocol_sha256": digest(protocol),
        "PRODUCT_SHA": head,
        "RECIPE_SHA256": digest(recipe),
        "DATASET_SHA256": digest(dataset),
        "ENV_FINGERPRINT_SHA256": digest(environment),
        "PROTOCOL_SHA256": digest(protocol),
        "COMPARATOR_SHA256": digest(HERE / "c2_parameter_verdict_927c5de.py"),
        "tolerance_table_sha256": "2" * 64,
        "tensor_tolerances": {"x": 0.0},
        "self_sha256": None,
    }
    calibration["self_sha256"] = verdict.canonical_sha256(calibration)
    result = evidence / "calibration.json"
    result.write_text(json.dumps(calibration))
    args = Namespace(
        product=product,
        recipe=recipe,
        dataset=dataset,
        environment=environment,
        protocol=protocol,
        comparator=HERE / "c2_parameter_verdict_927c5de.py",
        expected_steps=48,
        out=tmp_path / "locks",
        calibration_result=result,
        evidence_repo=evidence,
    )
    with pytest.raises(ValueError, match="uncommitted"):
        campaign.cmd_measurement_lock(args)
    subprocess.run(["git", "-C", str(evidence), "add", "calibration.json"], check=True)
    subprocess.run(["git", "-C", str(evidence), "commit", "-qm", "calibration"], check=True)
    assert campaign.cmd_measurement_lock(args) == 0
    lock = campaign.load_lock(args.out / "P_MEASUREMENT_LOCK.json")
    assert lock["ARM_ORDER"] == campaign.MEASUREMENT_ARMS


def _lineage_fixture(tmp_path, monkeypatch):
    for name in ("megatron", "megatron.core"):
        module = types.ModuleType(name)
        module.__spec__ = importlib.machinery.ModuleSpec(name, None)
        module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)
    lock = seal(base_lock())
    lock_sha = "9" * 64
    arm = tmp_path / "P-C1-off"
    run = arm / "checkpoints" / "sft" / arm.name
    checkpoint = run / "iter_00000048"
    checkpoint.mkdir(parents=True)
    dcp_save({"weight": torch.tensor([1.0, 2.0])}, storage_writer=FileSystemWriter(checkpoint), no_dist=True)
    (run / "latest_checkpointed_iteration.txt").write_text("48\n")
    log_lines = []
    for index in range(48):
        log_lines.append(
            f"step {index}: {{'train/step': {index}, 'train/loss': 1.0, 'train/grad_norm': 1.0, "
            "'train/lr-main': 0.001}"
        )
        log_lines.append(f"perf {index}: {{'perf/actor_train_tokens': 32, 'perf/train_time': 1.0}}")
    (arm / "job.log").write_text("\n".join(log_lines) + "\n")
    from extract_c2_native import parse_arm

    manifest = {
        "run_id": arm.name,
        "lock_sha256": lock_sha,
        "product_sha": lock["PRODUCT_SHA"],
        "recipe_sha256": lock["RECIPE_SHA256"],
        "dataset_sha256": lock["DATASET_SHA256"],
        "env_fingerprint_sha256": lock["ENV_FINGERPRINT_SHA256"],
        "protocol_sha256": lock["PROTOCOL_SHA256"],
        "runner_sha256": lock["RUNNER_SHA256"],
        "comparator_sha256": lock["COMPARATOR_SHA256"],
        "expected_steps": 48,
        "job_status": "SUCCEEDED",
        "valid": True,
        "resources_returned": True,
        "driver_source_sha256_before": "source",
        "driver_source_sha256_after": "source",
        "worker_source_hashes": {"worker": "source"},
        "native": parse_arm(arm, expected_steps=48),
    }
    (arm / "manifest.json").write_text(json.dumps(manifest))
    adapted = arm / "adapted"
    adapter.convert(arm / "checkpoints", adapted, arm_name=arm.name)
    lineage = campaign.validate_adapter_source(arm, adapted, lock, lock_sha)
    output = arm / "inventory.json"
    inventory.export_inventory(
        adapted,
        output,
        identity={**lock, "LOCK_SHA256": lock_sha},
        arm_name=arm.name,
        lineage=lineage,
    )
    return arm, lock, lock_sha, output


def test_formal_inventory_binds_arm_dcp_adapter_and_tensor_payload(tmp_path, monkeypatch):
    arm, lock, lock_sha, output = _lineage_fixture(tmp_path, monkeypatch)
    campaign.validate_inventory_lineage(output, arm, lock, lock_sha)
    with pytest.raises(ValueError, match="outside its frozen arm"):
        campaign.validate_inventory_lineage(output, tmp_path / "P-C2-off", lock, lock_sha)
    source = arm / "checkpoints" / "sft" / arm.name / "iter_00000048" / "__0_0.distcp"
    source.write_bytes(source.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="source DCP tree hash mismatch"):
        campaign.validate_inventory_lineage(output, arm, lock, lock_sha)


def test_formal_inventory_rejects_manifest_or_adapter_substitution(tmp_path, monkeypatch):
    arm, lock, lock_sha, output = _lineage_fixture(tmp_path, monkeypatch)
    record = arm / "adapted" / "ADAPTER_RECORD.json"
    payload = json.loads(record.read_text())
    payload["arm_name"] = "P-C2-off"
    record.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="adapter identity or arm mismatch"):
        campaign.validate_inventory_lineage(output, arm, lock, lock_sha)

    payload["arm_name"] = arm.name
    record.write_text(json.dumps(payload))
    manifest = arm / "manifest.json"
    changed = json.loads(manifest.read_text())
    changed["dataset_sha256"] = "0" * 64
    manifest.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="dataset_sha256 drift"):
        campaign.validate_inventory_lineage(output, arm, lock, lock_sha)


def test_formal_inventory_rejects_short_completed_job(tmp_path, monkeypatch):
    arm, lock, lock_sha, output = _lineage_fixture(tmp_path, monkeypatch)
    log = arm / "job.log"
    log.write_text("\n".join(log.read_text().splitlines()[:-2]) + "\n")
    with pytest.raises(ValueError, match="completed-step"):
        campaign.validate_inventory_lineage(output, arm, lock, lock_sha)
