#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Tiny, CPU-only relocation fixtures; no production artifacts or GPU jobs."""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest


HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import c2_parameter_dcp_adapter_927c5de as adapter  # noqa: E402
import c2_parameter_inventory_927c5de as inventory  # noqa: E402
import c2_parameter_replay_927c5de as replay  # noqa: E402
from extract_c2_native import parse_arm  # noqa: E402


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def commit(root):
    git(root, "add", ".")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
    return git(root, "rev-parse", "HEAD")


def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    repo, product, data = (tmp_path / name for name in ("repo", "product", "data"))
    for root in (repo, product, data):
        root.mkdir()
    git(repo, "init", "-q")
    git(product, "init", "-q")
    tools = repo / "evidence/tools"
    tools.mkdir(parents=True)
    for path in HERE.glob("*.py"):
        shutil.copyfile(path, tools / path.name)
    source = product / "relax/utils/straggler/x.py"
    source.parent.mkdir(parents=True)
    source.write_text("# fixture\n")
    recipe = product / "recipe.sh"
    recipe.write_text("# fixture recipe\n")
    product_sha = commit(product)
    base = repo / replay.BASE
    base.mkdir(parents=True)
    calibration = {
        "status": "FROZEN_OFF_ONLY",
        "product_sha": product_sha,
        "protocol_sha256": "b" * 64,
        "tensor_tolerances": {"weight": 0.25},
        "tolerance_table_sha256": "c" * 64,
        "self_sha256": None,
    }
    protocol = repo / "protocol.md"
    protocol.write_text("fixture protocol\n")
    calibration["protocol_sha256"] = replay.bounded.sha256_file(protocol)
    calibration["self_sha256"] = replay.frozen.canonical_sha256(calibration)
    calibration_path = base / "P_CALIBRATION_RESULT.json"
    write(calibration_path, calibration)
    calibration_commit = commit(repo)
    dataset = data / "dataset.json"
    dataset.write_text("[]\n")
    environment = data / "environment.json"
    environment.write_text("{}\n")
    lock = {
        "SCHEMA": "C2_PARAMETER_CAMPAIGN_927C5DE/v1",
        "STAGE": "MEASUREMENT",
        "PRODUCT_SHA": product_sha,
        "EXPECTED_STEPS": 1,
        "SAVE": 1,
        "CHECKPOINT_POLICY": "RETAIN_UNTIL_ARCHIVED",
        "TOPOLOGY": {"kind": "DP4", "gpus": 4},
        "ARM_ORDER": replay.campaign.MEASUREMENT_ARMS,
        "RECIPE_ENV": {"NUM_ROLLOUT": "1"},
        "CALIBRATION_RESULT_SHA256": replay.bounded.sha256_file(calibration_path),
        "CALIBRATION_RESULT_COMMIT": calibration_commit,
        "TOLERANCE_TABLE_SHA256": "c" * 64,
    }
    bindings = {
        "RECIPE": (recipe, replay.OLD_PRODUCT / "recipe.sh"),
        "DATASET": (dataset, replay.OLD_DATA / "dataset.json"),
        "ENV_FINGERPRINT": (environment, replay.OLD_DATA / "environment.json"),
        "PROTOCOL": (protocol, replay.OLD_REPO / "protocol.md"),
        "RUNNER": (
            tools / "c2_parameter_campaign_927c5de.py",
            replay.OLD_REPO / "evidence/tools/c2_parameter_campaign_927c5de.py",
        ),
        "COMPARATOR": (
            tools / "c2_parameter_verdict_927c5de.py",
            replay.OLD_REPO / "evidence/tools/c2_parameter_verdict_927c5de.py",
        ),
        "ADAPTER": (
            tools / "c2_parameter_dcp_adapter_927c5de.py",
            replay.OLD_REPO / "evidence/tools/c2_parameter_dcp_adapter_927c5de.py",
        ),
    }
    for name, (actual, logical) in bindings.items():
        lock[name + "_PATH"] = str(logical)
        lock[name + "_SHA256"] = replay.bounded.sha256_file(actual)
    lock["_self_sha256"] = replay.campaign.canonical_hash(lock)
    lock_path = base / "locks/P_MEASUREMENT_LOCK.json"
    write(lock_path, lock)
    commit(repo)
    execution_path = base / "locks/P_EXECUTION_LOCK.json"
    replay.execution.create(repo, lock_path, calibration_path, list(tools.glob("*.py")), execution_path)
    commit(repo)
    root = data / replay.CAMPAIGN
    lock_sha = replay.bounded.sha256_file(lock_path)
    fingerprint = replay.campaign._source_fingerprint(product)
    for name in lock["ARM_ORDER"]:
        arm = root / name
        iteration = arm / "checkpoints/sft" / name / "iter_00000001"
        iteration.mkdir(parents=True)
        (iteration / ".metadata").write_bytes(b"fixture DCP metadata")
        (iteration / "data.distcp").write_bytes(b"fixture DCP shard")
        (iteration.parent / "latest_checkpointed_iteration.txt").write_text("1\n")
        (arm / "job.log").write_text(
            "step 0: {'train/step': 0, 'train/loss': 1.0, 'train/grad_norm': 1.0, 'train/lr-x': 0.1}\n"
            "perf 0: {'perf/actor_train_tokens': 32, 'perf/train_time': 1.0}\n"
        )
        manifest = {
            "run_id": name,
            "lock_sha256": lock_sha,
            "product_sha": product_sha,
            "expected_steps": 1,
            "job_status": "SUCCEEDED",
            "valid": True,
            "resources_returned": True,
            "driver_source_sha256_before": fingerprint,
            "driver_source_sha256_after": fingerprint,
            "worker_source_hashes": {"worker": fingerprint},
            "native": parse_arm(arm, 1),
        }
        for field in ("recipe", "dataset", "env_fingerprint", "protocol", "runner", "comparator", "adapter"):
            manifest[field + "_sha256"] = lock[field.upper() + "_SHA256"]
        write(arm / "manifest.json", manifest)
        adapted = arm / "adapted"
        adapted.mkdir()
        raw = arm / "adapted_raw/raw.pt"
        raw.parent.mkdir()
        raw.write_bytes(b"fixture raw converted payload")
        (adapted / "converted_tensors.pt").write_bytes(b"fixture sanitized payload")
        logical = replay.OLD_DATA / replay.CAMPAIGN / name
        record = {
            "schema": "C2_927C5DE_DCP_ADAPTER/v1",
            "status": "REVIEWED_TRUSTED_CAMPAIGN_ONLY",
            "arm_name": name,
            "adapter_sha256": lock["ADAPTER_SHA256"],
            "source_checkpoint_root": str(logical / "checkpoints"),
            "source_iteration_dir": str(logical / iteration.relative_to(arm)),
            "raw_converted_path": str(logical / raw.relative_to(arm)),
            "source_tree_sha256": adapter.tree_hash(iteration),
            "raw_converted_sha256": replay.bounded.sha256_file(raw),
            "sanitized_sha256": replay.bounded.sha256_file(adapted / "converted_tensors.pt"),
        }
        write(adapted / "ADAPTER_RECORD.json", record)
        payload = arm / "payload.npy"
        header = repr({"descr": "<f4", "fortran_order": False, "shape": (1,)}).encode()
        header += b" " * ((64 - (10 + len(header) + 1) % 64) % 64) + b"\n"
        payload.write_bytes(b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header + struct.pack("<f", 1.0))
        inv = {
            "schema_version": 2,
            "arm_name": name,
            "product_sha": product_sha,
            "lock_sha256": lock_sha,
            "checkpoint_root": str(logical / "adapted"),
            "checkpoint_tree_sha256": adapter.tree_hash(adapted),
            "lineage": {
                "arm_manifest_sha256": replay.bounded.sha256_file(arm / "manifest.json"),
                "adapter_record_sha256": replay.bounded.sha256_file(adapted / "ADAPTER_RECORD.json"),
                "source_tree_sha256": record["source_tree_sha256"],
                "sanitized_sha256": record["sanitized_sha256"],
            },
            "tensors": [
                {
                    "name": "weight",
                    "shape": [1],
                    "dtype": "float32",
                    "npy": "payload.npy",
                    "payload_sha256": replay.bounded.sha256_file(payload),
                }
            ],
            "self_sha256": None,
        }
        for field in ("recipe", "dataset", "env_fingerprint", "protocol", "comparator"):
            inv[field + "_sha256"] = lock[field.upper() + "_SHA256"]
        inv["self_sha256"] = inventory.self_hash(inv)
        write(arm / "inventory.json", inv)
    for pair_id in ("P-M1", "P-M2"):
        pair = {
            "pair_id": pair_id,
            "product_sha": product_sha,
            "protocol_sha256": lock["PROTOCOL_SHA256"],
            "calibration_sha256": lock["CALIBRATION_RESULT_SHA256"],
            "measurement_lock_sha256": lock_sha,
        }
        for side in ("off", "on"):
            pair[side + "_inventory"] = f"{pair_id}-{side}/inventory.json"
            pair[side + "_inventory_sha256"] = replay.bounded.sha256_file(root / pair[side + "_inventory"])
        write(root / f"{pair_id}_PAIR_MANIFEST.json", pair)
    monkeypatch.setattr(replay, "__file__", str(tools / Path(replay.__file__).name))
    return repo, product, data


def test_same_and_relocated_results_byte_equal(evidence, tmp_path, monkeypatch):
    roots = replay.Roots(*evidence)
    original = replay.result(roots, *replay.preflight(roots, metadata_only=False))
    calibration_path = evidence[0] / replay.BASE / "P_CALIBRATION_RESULT.json"
    pair_paths = [evidence[2] / replay.CAMPAIGN / f"P-M{index}_PAIR_MANIFEST.json" for index in (1, 2)]
    frozen_output = tmp_path / "original-bounded-result.json"
    assert (
        replay.bounded.run(Namespace(calibration=str(calibration_path), pair_manifest=pair_paths, out=frozen_output))
        == 0
    )
    baseline = json.loads(frozen_output.read_text())
    baseline["calibration_path"] = str(replay.OLD_REPO / replay.BASE / "P_CALIBRATION_RESULT.json")
    baseline["self_sha256"] = replay.frozen.canonical_sha256(baseline)
    assert json.dumps(original, indent=2, sort_keys=True) == json.dumps(baseline, indent=2, sort_keys=True)
    targets = tuple(tmp_path / ("moved-" + path.name) for path in evidence)
    for old, new in zip(evidence, targets):
        shutil.copytree(old, new)
    monkeypatch.setattr(replay, "__file__", str(targets[0] / "evidence/tools/c2_parameter_replay_927c5de.py"))
    moved = replay.Roots(*targets)
    recovered = replay.result(moved, *replay.preflight(moved, metadata_only=False))
    assert json.dumps(original, indent=2, sort_keys=True) == json.dumps(recovered, indent=2, sort_keys=True)
    assert recovered["verdict"] == "PASS"
    assert recovered["calibration_path"].startswith(str(replay.OLD_REPO))


@pytest.mark.parametrize(
    "case",
    [
        "source",
        "commit",
        "lock",
        "identity",
        "missing",
        "duplicate",
        "raw",
        "dcp",
        "sanitized",
        "payload",
        "path",
        "calibration",
        "adapter",
        "product",
        "missing_payload",
    ],
)
def test_full_lineage_refuses_tampering(evidence, case):
    repo, product, data = evidence
    arm = data / replay.CAMPAIGN / "P-M1-off"
    if case == "source":
        (repo / "evidence/tools/c2_parameter_bounded_927c5de.py").write_text("tamper\n")
    elif case == "commit":
        path = repo / replay.BASE / "locks/P_EXECUTION_LOCK.json"
        value = json.loads(path.read_text())
        next(iter(value["sources"].values()))["commit"] = "a" * 40
        value["self_sha256"] = replay.frozen.canonical_sha256(value)
        write(path, value)
        commit(repo)
    elif case == "lock":
        (repo / replay.BASE / "locks/P_MEASUREMENT_LOCK.json").write_text("{}\n")
    elif case == "missing":
        (arm / "adapted/converted_tensors.pt").unlink()
    elif case == "missing_payload":
        (arm / "payload.npy").unlink()
    elif case == "calibration":
        (repo / replay.BASE / "P_CALIBRATION_RESULT.json").write_text("{}\n")
    elif case == "product":
        (product / "relax/utils/straggler/x.py").write_text("tamper\n")
    elif case == "adapter":
        path = arm / "adapted/ADAPTER_RECORD.json"
        value = json.loads(path.read_text())
        value["status"] = "UNREVIEWED"
        write(path, value)
    elif case in {"raw", "dcp", "sanitized", "payload"}:
        relative = {
            "raw": "adapted_raw/raw.pt",
            "dcp": "checkpoints/sft/P-M1-off/iter_00000001/data.distcp",
            "sanitized": "adapted/converted_tensors.pt",
            "payload": "payload.npy",
        }[case]
        (arm / relative).write_bytes(b"tamper")
    else:
        path = arm / "inventory.json"
        value = json.loads(path.read_text())
        if case == "identity":
            value["product_sha"] = "a" * 40
        elif case == "duplicate":
            value["tensors"].append(value["tensors"][0].copy())
        else:
            value["checkpoint_root"] = "/outside/owned/roots"
        value["self_sha256"] = inventory.self_hash(value)
        write(path, value)
        pair_path = data / replay.CAMPAIGN / "P-M1_PAIR_MANIFEST.json"
        pair = json.loads(pair_path.read_text())
        pair["off_inventory_sha256"] = replay.bounded.sha256_file(path)
        write(pair_path, pair)
    with pytest.raises((ValueError, OSError, replay.frozen.InvalidError, replay.frozen.IncompleteError)):
        replay.preflight(replay.Roots(repo, product, data), metadata_only=False)


def test_roots_reject_aliases_nested_roots_traversal_and_symlink(tmp_path):
    paths = [tmp_path / name for name in ("repo", "product", "data")]
    for path in paths:
        path.mkdir()
    with pytest.raises(ValueError):
        replay.Roots(paths[0], paths[0], paths[2])
    nested = paths[0] / "nested"
    nested.mkdir()
    with pytest.raises(ValueError):
        replay.Roots(paths[0], nested, paths[2])
    roots = replay.Roots(*paths)
    (paths[2] / "escape").symlink_to(tmp_path)
    for value in (replay.OLD_DATA / "escape/file", replay.OLD_DATA / "../file", Path("/wrong/root/file")):
        with pytest.raises(ValueError):
            roots.path(value)


def test_duplicate_json_keys_refused(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"key": 1, "key": 2}')
    with pytest.raises(ValueError, match="duplicate JSON key"):
        replay.strict_json(path)


def test_private_scopes_do_not_patch_original_modules(evidence):
    original_path = replay.campaign.Path
    original_resolve = replay.frozen.resolve_relative
    roots = replay.Roots(*evidence)
    replay.result(roots, *replay.preflight(roots, metadata_only=False))
    assert replay.campaign.Path is original_path
    assert replay.frozen.resolve_relative is original_resolve
