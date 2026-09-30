#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Regression tests for the 927c5de retained-tensor C2 comparator."""

from __future__ import annotations

import hashlib
import json
import pathlib
import struct
import sys

import pytest


HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

import c2_parameter_verdict_927c5de as verdict  # noqa: E402


PRODUCT = "a" * 40
PROTOCOL = "b" * 64
LOCK = "c" * 64


def write_json(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if "self_sha256" in payload:
        payload["self_sha256"] = verdict.canonical_sha256(payload)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def inventory(*, arm_name="P-M1-off", floats=(1.0, 2.0), integers=(3, 4), product=PRODUCT, protocol=PROTOCOL) -> dict:
    return {
        "arm_name": arm_name,
        "product_sha": product,
        "protocol_sha256": protocol,
        "lock_sha256": LOCK,
        "self_sha256": None,
        "tensors": [
            {"name": "float.weight", "shape": [2], "dtype": "float32", "values": list(floats)},
            {"name": "counter", "shape": [2], "dtype": "int64", "values": list(integers)},
        ],
    }


def calibration() -> dict:
    result = {
        "status": "FROZEN_OFF_ONLY",
        "product_sha": PRODUCT,
        "protocol_sha256": PROTOCOL,
        "tensor_tolerances": {"float.weight": 0.25},
        "self_sha256": None,
    }
    result["self_sha256"] = verdict.canonical_sha256(result)
    return result


def setup_case(tmp_path: pathlib.Path) -> tuple[pathlib.Path, list[pathlib.Path], pathlib.Path]:
    calibration_path = tmp_path / "calibration.json"
    write_json(calibration_path, calibration())
    calibration_sha = hashlib.sha256(calibration_path.read_bytes()).hexdigest()
    pairs = []
    for number in (1, 2):
        off = tmp_path / f"off-{number}.json"
        on = tmp_path / f"on-{number}.json"
        write_json(off, inventory(arm_name=f"P-M{number}-off"))
        write_json(on, inventory(arm_name=f"P-M{number}-on", floats=(1.1, 2.1)))
        pair = tmp_path / f"pair-{number}.json"
        write_json(
            pair,
            {
                "pair_id": f"P-M{number}",
                "product_sha": PRODUCT,
                "protocol_sha256": PROTOCOL,
                "calibration_sha256": calibration_sha,
                "measurement_lock_sha256": LOCK,
                "off_inventory": off.name,
                "on_inventory": on.name,
                "off_inventory_sha256": hashlib.sha256(off.read_bytes()).hexdigest(),
                "on_inventory_sha256": hashlib.sha256(on.read_bytes()).hexdigest(),
            },
        )
        pairs.append(pair)
    return calibration_path, pairs, tmp_path / "result.json"


def invoke(calibration_path, pairs, out):
    return verdict.run(
        type(
            "Args",
            (),
            {"calibration": str(calibration_path), "pair_manifest": [str(pair) for pair in pairs], "out": str(out)},
        )()
    )


def read_result(out):
    data = json.loads(out.read_text())
    assert data["self_sha256"] == verdict.canonical_sha256(data)
    return data


def refresh_pair_hash(pair_path: pathlib.Path, side: str) -> None:
    pair = json.loads(pair_path.read_text())
    target = pair_path.parent / pair[f"{side}_inventory"]
    pair[f"{side}_inventory_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    write_json(pair_path, pair)


def test_retained_tensor_pairs_pass_with_frozen_tolerances(tmp_path):
    calibration_path, pairs, out = setup_case(tmp_path)
    assert invoke(calibration_path, pairs, out) == 0
    result = read_result(out)
    assert result["verdict"] == "PASS"
    assert result["pairs"][0]["tensors"]["float.weight"]["max_abs_delta"] == pytest.approx(0.1)


def test_old_hash_only_path_now_rejects_missing_checkpoint_inventory(tmp_path):
    calibration_path, pairs, out = setup_case(tmp_path)
    json.loads(pairs[0].read_text())
    payload = json.loads(pairs[0].read_text())
    payload["off_inventory"] = "pruned-checkpoint-inventory.json"
    write_json(pairs[0], payload)
    assert invoke(calibration_path, pairs, out) == 1
    assert read_result(out)["verdict"] == "INCOMPLETE"


def test_floating_tolerance_breach_is_not_pass(tmp_path):
    calibration_path, pairs, out = setup_case(tmp_path)
    on = tmp_path / "on-1.json"
    write_json(on, inventory(arm_name="P-M1-on", floats=(1.3, 2.0)))
    refresh_pair_hash(pairs[0], "on")
    assert invoke(calibration_path, pairs, out) == 1
    result = read_result(out)
    assert result["verdict"] == "NOT_PASS"
    assert "float.weight" in result["reason"]


def test_nonfloating_difference_is_not_pass(tmp_path):
    calibration_path, pairs, out = setup_case(tmp_path)
    write_json(tmp_path / "on-2.json", inventory(arm_name="P-M2-on", integers=(3, 5)))
    refresh_pair_hash(pairs[1], "on")
    assert invoke(calibration_path, pairs, out) == 1
    assert read_result(out)["verdict"] == "NOT_PASS"


def test_identity_drift_is_invalid_not_a_silent_comparison(tmp_path):
    calibration_path, pairs, out = setup_case(tmp_path)
    payload = json.loads(pairs[0].read_text())
    payload["protocol_sha256"] = "c" * 64
    write_json(pairs[0], payload)
    assert invoke(calibration_path, pairs, out) == 2
    assert read_result(out)["verdict"] == "INVALID"


def test_missing_calibration_tolerance_is_incomplete(tmp_path):
    calibration_path, pairs, out = setup_case(tmp_path)
    data = calibration()
    data["tensor_tolerances"].pop("float.weight")
    data["self_sha256"] = verdict.canonical_sha256(data)
    write_json(calibration_path, data)
    calibration_sha = hashlib.sha256(calibration_path.read_bytes()).hexdigest()
    for pair in pairs:
        payload = json.loads(pair.read_text())
        payload["calibration_sha256"] = calibration_sha
        write_json(pair, payload)
    assert invoke(calibration_path, pairs, out) == 1
    assert read_result(out)["verdict"] == "INCOMPLETE"


def test_npy_payload_is_cpu_read_without_numpy(tmp_path):
    calibration_path, pairs, out = setup_case(tmp_path)
    npy = tmp_path / "float.npy"
    header = b"{'descr': '<f4', 'fortran_order': False, 'shape': (2,), }"
    padding = b" " * ((16 - ((10 + len(header) + 1) % 16)) % 16)
    header = header + padding + b"\n"
    npy.write_bytes(
        b"\x93NUMPY" + bytes((1, 0)) + struct.pack("<H", len(header)) + header + struct.pack("<ff", 1.1, 2.1)
    )
    on = inventory(arm_name="P-M1-on")
    on["tensors"][0].pop("values")
    on["tensors"][0]["npy"] = npy.name
    on["tensors"][0]["payload_sha256"] = hashlib.sha256(npy.read_bytes()).hexdigest()
    write_json(tmp_path / "on-1.json", on)
    refresh_pair_hash(pairs[0], "on")
    assert invoke(calibration_path, pairs, out) == 0
    assert read_result(out)["verdict"] == "PASS"


def test_result_is_non_overwriting(tmp_path):
    calibration_path, pairs, out = setup_case(tmp_path)
    assert invoke(calibration_path, pairs, out) == 0
    with pytest.raises(SystemExit, match="refusing to overwrite"):
        invoke(calibration_path, pairs, out)


def test_exactly_two_pairs_are_required_before_reading_inputs(tmp_path):
    calibration_path, pairs, out = setup_case(tmp_path)
    assert invoke(calibration_path, pairs[:1], out) == 2
    assert read_result(out)["verdict"] == "INVALID"


def test_measurement_cannot_pass_by_reusing_off_inventory_as_on(tmp_path):
    calibration_path, pairs, out = setup_case(tmp_path)
    for pair_path in pairs:
        pair = json.loads(pair_path.read_text())
        pair["on_inventory"] = pair["off_inventory"]
        write_json(pair_path, pair)
    assert invoke(calibration_path, pairs, out) == 2
    assert read_result(out)["verdict"] == "INVALID"


def test_measurement_rejects_claimed_inventory_hash_mismatch(tmp_path):
    calibration_path, pairs, out = setup_case(tmp_path)
    pair = json.loads(pairs[0].read_text())
    pair["off_inventory_sha256"] = "0" * 64
    write_json(pairs[0], pair)
    assert invoke(calibration_path, pairs, out) == 2
    assert read_result(out)["verdict"] == "INVALID"


def test_measurement_rejects_inventory_self_hash_mismatch(tmp_path):
    calibration_path, pairs, out = setup_case(tmp_path)
    on_path = tmp_path / "on-1.json"
    on = json.loads(on_path.read_text())
    on["self_sha256"] = "0" * 64
    on_path.write_text(json.dumps(on, sort_keys=True) + "\n")
    refresh_pair_hash(pairs[0], "on")
    assert invoke(calibration_path, pairs, out) == 2
    assert read_result(out)["verdict"] == "INVALID"


def test_measurement_rejects_npy_payload_hash_mismatch(tmp_path):
    calibration_path, pairs, out = setup_case(tmp_path)
    npy = tmp_path / "float.npy"
    header = b"{'descr': '<f4', 'fortran_order': False, 'shape': (2,), }"
    header += b" " * ((16 - ((10 + len(header) + 1) % 16)) % 16) + b"\n"
    npy.write_bytes(
        b"\x93NUMPY" + bytes((1, 0)) + struct.pack("<H", len(header)) + header + struct.pack("<ff", 1.1, 2.1)
    )
    on = inventory(arm_name="P-M1-on")
    on["tensors"][0].pop("values")
    on["tensors"][0]["npy"] = npy.name
    on["tensors"][0]["payload_sha256"] = "0" * 64
    write_json(tmp_path / "on-1.json", on)
    refresh_pair_hash(pairs[0], "on")
    assert invoke(calibration_path, pairs, out) == 2
    assert read_result(out)["verdict"] == "INVALID"


def test_measurement_rejects_reversed_pair_order(tmp_path):
    calibration_path, pairs, out = setup_case(tmp_path)
    assert invoke(calibration_path, list(reversed(pairs)), out) == 2
    assert read_result(out)["verdict"] == "INVALID"


def test_measurement_rejects_inventory_from_another_lock(tmp_path):
    calibration_path, pairs, out = setup_case(tmp_path)
    on_path = tmp_path / "on-1.json"
    on = json.loads(on_path.read_text())
    on["lock_sha256"] = "d" * 64
    write_json(on_path, on)
    refresh_pair_hash(pairs[0], "on")
    assert invoke(calibration_path, pairs, out) == 2
    assert read_result(out)["verdict"] == "INVALID"
