# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""CPU regression tests for the independent native-loss evidence gates."""

from __future__ import annotations

import importlib.util
import itertools
import sys
from pathlib import Path

import pytest


TOOL = Path(__file__).with_name("native_loss_gate_audit_927c5de.py")
sys.path.insert(0, str(TOOL.parent))
SPEC = importlib.util.spec_from_file_location("native_loss_gate_audit_927c5de", TOOL)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit
SPEC.loader.exec_module(audit)


def valid_lock(stage: str = "MEASUREMENT") -> dict:
    order = audit.CALIBRATION_ARMS if stage == "CALIBRATION" else audit.MEASUREMENT_ARMS
    value = {
        "schema": "TASK11_NATIVE_LOSS_CAMPAIGN/v1",
        "stage": stage,
        "product_sha": audit.PRODUCT_SHA,
        **{field: "a" * 64 for field in audit.BASE_HASH_FIELDS},
        "runtime": {field: "b" * 64 for field in audit.RUNTIME_HASH_FIELDS},
        "arm_order": list(order),
        "steps": audit.frozen.STEPS,
        "seed": audit.frozen.SEED,
        "save": 0,
        "on_profile": audit.frozen.ON_PROFILE,
        "_self_sha256": None,
    }
    if stage == "MEASUREMENT":
        value.update(
            {
                "measurement_runner_sha256": "c" * 64,
                "calibration_lock_sha256": "d" * 64,
                "calibration_result_sha256": "e" * 64,
                "calibration_result_commit": "f" * 40,
                "measurement_pairs": [list(pair) for pair in audit.EXPECTED_PAIRS],
            }
        )
    value["_self_sha256"] = audit.canonical_sha(value)
    return value


def valid_result(lock: dict | None = None) -> dict:
    calibration_lock = lock or valid_lock("CALIBRATION")
    pairs = [list(pair) for pair in itertools.combinations(audit.CALIBRATION_ARMS, 2)]
    result = {
        "schema": "TASK11_NATIVE_LOSS_CALIBRATION_RESULT/v1",
        "product_sha": audit.PRODUCT_SHA,
        "lock_sha256": calibration_lock["_self_sha256"],
        "arm_manifests": {name: "1" * 64 for name in audit.CALIBRATION_ARMS},
        "raw_argv_sha256": {name: "2" * 64 for name in audit.CALIBRATION_ARMS},
        "normalized_argv_sha256": "3" * 64,
        "contrasts": [
            {
                "pair": pair,
                "loss_series": {"max_abs_delta": 0.1, "step": 1},
                "grad_norm_series": {"max_abs_delta": 0.2, "step": 2},
            }
            for pair in pairs
        ],
        "tolerances": {"loss_series": 0.2, "grad_norm_series": 0.4},
        "_self_sha256": None,
    }
    result["_self_sha256"] = audit.canonical_sha(result)
    return result


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("measurement_runner_sha256", None),
        ("measurement_runner_sha256", ""),
        ("measurement_runner_sha256", "z" * 64),
        ("calibration_result_sha256", None),
        ("calibration_lock_sha256", ""),
    ],
)
def test_measurement_lock_rejects_missing_or_malformed_hashes(field: str, value: str | None) -> None:
    lock = valid_lock()
    lock[field] = value
    lock["_self_sha256"] = audit.canonical_sha(lock)
    with pytest.raises(audit.AuditFailure, match="SHA-256"):
        audit.validate_lock(lock, "MEASUREMENT")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda lock: lock.update(arm_order=lock["arm_order"][:-1]),
        lambda lock: lock.update(arm_order=[*lock["arm_order"][:-1], lock["arm_order"][0]]),
        lambda lock: lock.update(arm_order=list(reversed(lock["arm_order"]))),
        lambda lock: lock.update(measurement_pairs=[["L-M1-off", "L-M1-on"]]),
        lambda lock: lock.update(measurement_pairs=[["L-M1-on", "L-M1-off"], ["L-M2-off", "L-M2-on"]]),
        lambda lock: lock.update(measurement_pairs=[["L-M1-off", "L-M1-on"], ["L-M1-off", "L-M2-on"]]),
    ],
)
def test_lock_rejects_wrong_arm_count_order_duplicates_and_pairs(mutate) -> None:
    lock = valid_lock()
    mutate(lock)
    lock["_self_sha256"] = audit.canonical_sha(lock)
    with pytest.raises(audit.AuditFailure):
        audit.validate_lock(lock, "MEASUREMENT")


def test_calibration_result_rejects_bad_product_lock_or_missing_argv_hash() -> None:
    calibration_lock = valid_lock("CALIBRATION")
    measurement_lock = valid_lock("MEASUREMENT")
    measurement_lock["calibration_lock_sha256"] = calibration_lock["_self_sha256"]
    result = valid_result(calibration_lock)
    result["lock_sha256"] = "9" * 64
    result["_self_sha256"] = audit.canonical_sha(result)
    with pytest.raises(audit.AuditFailure, match="lineage"):
        audit.validate_calibration_result(result, calibration_lock, measurement_lock)

    result = valid_result(calibration_lock)
    result["raw_argv_sha256"].pop(audit.CALIBRATION_ARMS[-1])
    result["_self_sha256"] = audit.canonical_sha(result)
    with pytest.raises(audit.AuditFailure, match="raw argv"):
        audit.validate_calibration_result(result, calibration_lock, measurement_lock)


def test_missing_arm_directory_or_manifest_is_incomplete(tmp_path: Path) -> None:
    lock = valid_lock("CALIBRATION")
    with pytest.raises(audit.AuditFailure) as missing_arm:
        audit.audit_arm(tmp_path, tmp_path / "missing", audit.CALIBRATION_ARMS[0], lock, "3" * 64, {})
    assert missing_arm.value.status == "INCOMPLETE"

    arm_dir = tmp_path / audit.CALIBRATION_ARMS[0]
    arm_dir.mkdir()
    with pytest.raises(audit.AuditFailure) as missing_manifest:
        audit.audit_arm(tmp_path, arm_dir, arm_dir.name, lock, "3" * 64, {})
    assert missing_manifest.value.status == "INCOMPLETE"


def test_json_with_duplicate_object_keys_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"stage":"CALIBRATION","stage":"MEASUREMENT"}')
    with pytest.raises(audit.AuditFailure, match="duplicate JSON object key"):
        audit.read_json(path, "duplicate fixture")


@pytest.mark.parametrize("filename", ["manifest.json", "job.log", "train-argv.nul"])
def test_campaign_inputs_cannot_escape_raw_root_through_symlinks(tmp_path: Path, filename: str) -> None:
    root = tmp_path / "raw"
    arm_dir = root / "L-M1-on"
    arm_dir.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_text("outside data")
    target = arm_dir / filename
    target.symlink_to(outside)
    with pytest.raises(audit.AuditFailure, match="escapes --raw-root"):
        audit.secure_campaign_path(root, target, filename)


def test_report_write_is_exclusive_and_preserves_existing_file(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    existing = tmp_path / "existing.md"
    existing.write_text("original")
    with pytest.raises(audit.AuditFailure, match="refusing to overwrite"):
        audit.write_report_once(existing, "replacement", raw_root)
    assert existing.read_text() == "original"

    new = tmp_path / "new.md"
    audit.write_report_once(new, "report", raw_root)
    assert new.read_text() == "report"

    with pytest.raises(audit.AuditFailure, match="outside the read-only"):
        audit.write_report_once(raw_root / "report.md", "report", raw_root)


def valid_native() -> dict:
    return {
        "arm": "L-M1-off",
        "native_valid": True,
        "extraction_errors": [],
        "nan_inf_findings": [],
        "native_step_ids": list(range(audit.frozen.STEPS)),
        "update_count": audit.frozen.STEPS,
        "step_ids_contiguous": True,
        "loss_series": [0.1] * audit.frozen.STEPS,
        "grad_norm_series": [1.0] * audit.frozen.STEPS,
        "token_series": [32] * audit.frozen.STEPS,
        "train_time_series": [1.0] * audit.frozen.STEPS,
        "learning_rate_series": [{"train/lr-decay": 1e-5}] * audit.frozen.STEPS,
    }


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda item: item.update(native_step_ids=item["native_step_ids"][:-1]), "step IDs"),
        (
            lambda item: item.update(native_step_ids=[0, 0, *range(2, audit.frozen.STEPS)]),
            "step IDs",
        ),
        (lambda item: item.update(extraction_errors=[{"kind": "duplicate native step"}]), "duplicate"),
        (lambda item: item["loss_series"].__setitem__(4, float("nan")), "nonfinite"),
        (lambda item: item["grad_norm_series"].__setitem__(4, float("inf")), "nonfinite"),
        (lambda item: item.update(nan_inf_findings=[{"line": 1}]), "NaN/Inf"),
    ],
)
def test_native_series_rejects_short_duplicate_and_nonfinite_data(mutate, message: str) -> None:
    item = valid_native()
    mutate(item)
    with pytest.raises(audit.AuditFailure, match=message):
        audit.validate_numeric_series(item, "L-M1-off")


def test_training_argv_must_match_after_only_tensorboard_name_normalization() -> None:
    calibration = b"--seed\x001234\x00--lr\x001e-5\x00--tb-experiment-name\x00off\x00"
    same_training_different_name = b"--seed\x001234\x00--lr\x001e-5\x00--tb-experiment-name\x00on\x00"
    changed_training = b"--seed\x001234\x00--lr\x002e-5\x00--tb-experiment-name\x00on\x00"
    _, expected = audit.normalize_argv(calibration)
    assert audit.normalize_argv(same_training_different_name)[1] == expected
    assert audit.normalize_argv(changed_training)[1] != expected


def test_on_requires_runtime_start_and_enable_evidence_for_both_roles() -> None:
    on_manifest = {"launch_spec": {"observer": audit.frozen.ON_PROFILE}}
    off_manifest = {"launch_spec": {"observer": {}}}
    with pytest.raises(audit.AuditFailure, match="lacks sender/collector"):
        audit.validate_observer("L-M1-on", on_manifest, "training completed")
    with pytest.raises(audit.AuditFailure, match="OFF log contains"):
        audit.validate_observer("L-M1-off", off_manifest, "straggler profiler enabled: role=sender")

    active_log = "\n".join(
        [
            "straggler profiler started: role=sender identity=rank1 collector=127.0.0.1:1234",
            "straggler profiler started: role=collector identity=rank0 collector=127.0.0.1:1234",
            "straggler profiler enabled: role=sender, log_level=2, window=5.0s",
            "straggler profiler enabled: role=collector, log_level=2, window=5.0s",
        ]
    )
    assert audit.validate_observer("L-M1-on", on_manifest, active_log)["activation_roles"] == [
        "collector",
        "sender",
    ]


def test_boundary_is_inclusive_and_valid_exceedance_is_not_pass() -> None:
    def arm(name: str, loss: float) -> dict:
        native = valid_native()
        native["arm"] = name
        native["loss_series"] = [loss] * audit.frozen.STEPS
        return {"normalized_argv_sha256": "a" * 64, "native": native}

    tolerances = {"loss_series": 0.5, "grad_norm_series": 0.0}
    accepted = audit.compare_pairs(
        {"L-M1-off": arm("L-M1-off", 0.0), "L-M1-on": arm("L-M1-on", 0.5)},
        tolerances,
        (("L-M1-off", "L-M1-on"),),
    )
    assert accepted[0]["status"] == "PASS"
    rejected = audit.compare_pairs(
        {"L-M1-off": arm("L-M1-off", 0.0), "L-M1-on": arm("L-M1-on", 0.500001)},
        tolerances,
        (("L-M1-off", "L-M1-on"),),
    )
    assert rejected[0]["status"] == "NOT_PASS"


def test_self_hash_tampering_is_rejected() -> None:
    lock = valid_lock()
    lock["dataset_sha256"] = "9" * 64
    with pytest.raises(audit.AuditFailure, match="self-hash mismatch"):
        audit.validate_lock(lock, "MEASUREMENT")
