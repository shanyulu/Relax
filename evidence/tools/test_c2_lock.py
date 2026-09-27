#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Unit tests for c2_lock.py stage logic (read_arm monkeypatched).

Pins the frozen tolerance policy: determinism detection, the 2x OFF/OFF
envelope, measurement-lock sha-referencing, and the compare verdicts in both
modes. Run: python -m pytest test_c2_lock.py -q
"""

import hashlib
import json
import pathlib
import shutil
import sys

import pytest


HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

import c2_lock as lk  # noqa: E402


TMP = pathlib.Path("/tmp/opencode/c2_lock_tests")


def arm(name, *, loss=None, grad=None, tokens=None, update_count=48, ckpt="a"):
    return {
        "update_count": update_count,
        "loss_series": loss if loss is not None else [1.0] * 48,
        "grad_norm_series": grad if grad is not None else [2.0] * 48,
        "learning_rate_series": tokens if tokens is not None else [{"lr": 1.0}] * 48,
        "token_series": tokens if tokens is not None else [4913] * 48,
        "checkpoint_tree_sha256": ckpt,
        "native_valid": True,
    }


def write_json(path, payload):
    if payload.get("status") == "FROZEN_OFF_ONLY":
        payload = {
            "PRODUCT_SHA": "a" * 40,
            "DATASET_SHA256": "f" * 64,
            "RECIPE_SHA256": "e" * 64,
            "ENV_FINGERPRINT_SHA256": "9" * 64,
            "EXPECTED_STEPS": 48,
            **payload,
        }
    if "_self_sha256" in payload:
        payload = {
            "DATASET_SHA256": "f" * 64,
            "RECIPE_SHA256": "e" * 64,
            "ENV_FINGERPRINT_SHA256": "9" * 64,
            "EXPECTED_STEPS": 48,
            "ARM_ORDER": ["C2M1-off", "C2M1-on"],
            **payload,
        }
        payload["_self_sha256"] = None
        payload["_self_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def setup_case(name, calib_arms, meas_off, meas_on, *, mode=None):
    root = TMP / name
    if root.exists():
        shutil.rmtree(root)
    lock = {
        "PRODUCT_SHA": "a" * 40,
        "DATASET_SHA256": "f" * 64,
        "RECIPE_SHA256": "e" * 64,
        "ENV_FINGERPRINT_SHA256": "9" * 64,
        "EXPECTED_STEPS": 48,
        "ARM_ORDER": [f"C2C{i}-off" for i in range(1, 7)],
        "_self_sha256": "self",
    }
    write_json(root / "calibration_lock.json", lock)
    calib_arms_payload = {
        "status": "FROZEN_OFF_ONLY",
        "mode": mode,
        "envelope_semantics": "declared",
        "steps_per_series": 48,
        "DATASET_SHA256": "f" * 64,
        "RECIPE_SHA256": "e" * 64,
        "ENV_FINGERPRINT_SHA256": "9" * 64,
        "PRODUCT_SHA": "a" * 40,
        "tolerances": {"mode": mode},
        "MEASUREMENT_N_PAIRS": None,
    }
    calib_arms_payload.pop("MEASUREMENT_N_PAIRS")
    write_json(root / "calibration_result.json", calib_arms_payload)
    return root, lock


@pytest.fixture
def patch_read(monkeypatch):
    def install(store):
        def fake_read(arm_dir, lock):
            return store[arm_dir.name]

        monkeypatch.setattr(lk, "read_arm", fake_read)

    return install


def test_envelope_is_two_times_worst_off_off_delta(patch_read, tmp_path):
    base = [1.0] * 48
    noisy = [1.0] * 47 + [1.5]
    store = {f"C2C{i}-off": arm(f"C2C{i}", loss=base, ckpt=f"c{i}") for i in range(1, 7)}
    store["C2C2-off"] = arm("C2C2", loss=noisy, ckpt="c2")
    patch_read(store)
    root = tmp_path
    lock = {
        "PRODUCT_SHA": "a" * 40,
        "ARM_ORDER": list(store),
        "EXPECTED_STEPS": 48,
        "RECIPE_PATH": "recipe.sh",
        "_self_sha256": None,
    }
    write_json(root / "lock.json", lock)
    out = root / "result.json"
    from argparse import Namespace

    assert lk.cmd_calibration_result(Namespace(lock=root / "lock.json", campaign=root, out=out)) == 0
    result = json.loads(out.read_text())
    assert result["envelope"]["loss_series"] == 0.5
    assert result["tolerances"]["loss_series"] == 1.0


def test_measurement_lock_references_calibration_sha(tmp_path, monkeypatch):
    calib = {
        "status": "FROZEN_OFF_ONLY",
        "mode": "OFF_OFF_ENVELOPE",
        "tolerances": {"mode": "OFF_OFF_ENVELOPE_x2", "loss_series": 1.0},
        "envelope_semantics": "declared",
    }
    calib_path = tmp_path / "calibration_result.json"
    write_json(calib_path, calib)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "c2_lock.py",
            "measurement-lock",
            "--calibration-result",
            str(calib_path),
            "--out",
            str(out_dir),
            "--n-pairs",
            "2",
        ],
    )
    assert lk.main() == 0
    lock = json.loads((out_dir / "C2_MEASUREMENT_LOCK.json").read_text())
    assert lock["CALIBRATION_RESULT_SHA256"] == hashlib.sha256(calib_path.read_bytes()).hexdigest()
    assert lock["TOLERANCES"]["loss_series"] == 1.0
    assert lock["ARM_ORDER"] == ["C2M1-off", "C2M1-on", "C2M2-on", "C2M2-off"]


def test_measurement_lock_rejects_unfrozen_calibration(tmp_path, monkeypatch):
    calib = {"status": "DRAFT", "mode": "OFF_OFF_ENVELOPE", "tolerances": {"mode": "OFF_OFF_ENVELOPE_x2"}}
    calib_path = tmp_path / "calibration_result.json"
    write_json(calib_path, calib)
    out_dir = tmp_path / "out2"
    out_dir.mkdir()
    monkeypatch.setattr(
        sys, "argv", ["c2_lock.py", "measurement-lock", "--calibration-result", str(calib_path), "--out", str(out_dir)]
    )
    with pytest.raises(SystemExit):
        lk.main()


def test_compare_exact_mode_flags_any_drift(tmp_path, monkeypatch):
    calib = {
        "status": "FROZEN_OFF_ONLY",
        "mode": "EXACT_EQUALITY",
        "steps_per_series": 48,
        "DATASET_SHA256": "f" * 64,
        "RECIPE_SHA256": "e" * 64,
        "ENV_FINGERPRINT_SHA256": "9" * 64,
        "PRODUCT_SHA": "a" * 40,
        "tolerances": {"mode": "EXACT_EQUALITY"},
        "envelope_semantics": None,
    }
    calib_path = tmp_path / "calibration_result.json"
    write_json(calib_path, calib)
    lock = {
        "CALIBRATION_RESULT_SHA256": hashlib.sha256(calib_path.read_bytes()).hexdigest(),
        "MEASUREMENT_N_PAIRS": 1,
        "PRODUCT_SHA": "a" * 40,
        "TOLERANCES": {"mode": "EXACT_EQUALITY"},
        "_self_sha256": "self",
    }
    lock_path = tmp_path / "measurement_lock.json"
    write_json(lock_path, lock)
    store = {
        "C2M1-off": arm("off", loss=[1.0] * 48, ckpt="x"),
        "C2M1-on": arm("on", loss=[1.0] * 47 + [1.0000001], ckpt="x"),
    }
    monkeypatch.setattr(lk, "read_arm", lambda arm_dir, lck: store[arm_dir.name])
    out = tmp_path / "compare.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "c2_lock.py",
            "compare",
            "--lock",
            str(lock_path),
            "--calibration-result",
            str(calib_path),
            "--campaign",
            str(tmp_path),
            "--out",
            str(out),
        ],
    )
    assert lk.main() == 1
    result = json.loads(out.read_text())
    assert result["verdict"] == "NOT_PASS"
    assert any("loss_series" in v for v in result["violations"])


def test_compare_envelope_cannot_replace_parameter_comparison(tmp_path, monkeypatch):
    calib = {
        "status": "FROZEN_OFF_ONLY",
        "mode": "OFF_OFF_ENVELOPE",
        "steps_per_series": 48,
        "DATASET_SHA256": "f" * 64,
        "RECIPE_SHA256": "e" * 64,
        "ENV_FINGERPRINT_SHA256": "9" * 64,
        "PRODUCT_SHA": "a" * 40,
        "tolerances": {"mode": "OFF_OFF_ENVELOPE_x2", "loss_series": 1.0, "grad_norm_series": 2.0, "token_series": 0},
        "envelope_semantics": "declared",
    }
    calib_path = tmp_path / "calibration_result.json"
    write_json(calib_path, calib)
    lock = {
        "CALIBRATION_RESULT_SHA256": hashlib.sha256(calib_path.read_bytes()).hexdigest(),
        "MEASUREMENT_N_PAIRS": 1,
        "PRODUCT_SHA": "a" * 40,
        "TOLERANCES": calib["tolerances"],
        "_self_sha256": "self",
    }
    lock_path = tmp_path / "measurement_lock.json"
    write_json(lock_path, lock)
    store = {
        "C2M1-off": arm("off", loss=[1.0] * 48, ckpt="x"),
        "C2M1-on": arm("on", loss=[1.0] * 47 + [1.6], ckpt="y"),
    }
    monkeypatch.setattr(lk, "read_arm", lambda arm_dir, lck: store[arm_dir.name])
    out = tmp_path / "compare.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "c2_lock.py",
            "compare",
            "--lock",
            str(lock_path),
            "--calibration-result",
            str(calib_path),
            "--campaign",
            str(tmp_path),
            "--out",
            str(out),
        ],
    )
    assert lk.main() == 1
    result = json.loads(out.read_text())
    assert result["verdict"] == "INCOMPLETE"
    assert result["missing_evidence"] == ["C2M1:parameter_equivalence"]
    assert result["pairs"]["C2M1"]["loss_series"]["max_abs_delta"] == pytest.approx(0.6)


@pytest.mark.parametrize(
    "off,on,exact,expected",
    [
        (None, None, False, "NOT_MEASURED"),
        ("a", "b", False, "NOT_MEASURED"),
        ("a", "b", True, "NOT_PASS"),
        ("a", "a", True, "PASS"),
        ("a", "a", False, "PASS"),
    ],
)
def test_checkpoint_gate_fails_closed(off, on, exact, expected):
    assert lk.checkpoint_gate(off, on, exact) == expected


def test_compare_rejects_wrong_calibration_reference(tmp_path, monkeypatch):
    calib = {"status": "FROZEN_OFF_ONLY", "mode": "EXACT_EQUALITY", "tolerances": {"mode": "EXACT_EQUALITY"}}
    calib_path = tmp_path / "calibration_result.json"
    write_json(calib_path, calib)
    lock = {
        "CALIBRATION_RESULT_SHA256": "0" * 64,
        "MEASUREMENT_N_PAIRS": 1,
        "PRODUCT_SHA": "a" * 40,
        "TOLERANCES": {"mode": "EXACT_EQUALITY"},
        "_self_sha256": "s",
    }
    lock_path = tmp_path / "measurement_lock.json"
    write_json(lock_path, lock)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "c2_lock.py",
            "compare",
            "--lock",
            str(lock_path),
            "--calibration-result",
            str(calib_path),
            "--campaign",
            str(tmp_path),
            "--out",
            str(tmp_path / "c.json"),
        ],
    )
    assert lk.main() == 2
    assert json.loads((tmp_path / "c.json").read_text())["verdict"] == "INVALID"


def test_no_overwrite_of_frozen_artifacts(tmp_path, monkeypatch):
    out = tmp_path / "existing.json"
    out.write_text("{}")
    calib = {
        "status": "FROZEN_OFF_ONLY",
        "mode": "EXACT_EQUALITY",
        "steps_per_series": 48,
        "tolerances": {"mode": "EXACT_EQUALITY"},
    }
    calib_path = tmp_path / "calibration_result.json"
    write_json(calib_path, calib)
    lock = {
        "CALIBRATION_RESULT_SHA256": hashlib.sha256(calib_path.read_bytes()).hexdigest(),
        "MEASUREMENT_N_PAIRS": 1,
        "PRODUCT_SHA": "a" * 40,
        "TOLERANCES": {"mode": "EXACT_EQUALITY"},
        "_self_sha256": "s",
    }
    lock_path = tmp_path / "measurement_lock.json"
    write_json(lock_path, lock)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "c2_lock.py",
            "compare",
            "--lock",
            str(lock_path),
            "--calibration-result",
            str(calib_path),
            "--campaign",
            str(tmp_path),
            "--out",
            str(out),
        ],
    )
    with pytest.raises(SystemExit):
        lk.main()
