#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Golden-output and fail-closed tests for bounded parameter execution."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import pytest


sys.path.insert(0, str(pathlib.Path(__file__).parent))

import c2_parameter_bounded_927c5de as bounded  # noqa: E402
import c2_parameter_calibration_927c5de as calibration  # noqa: E402
import c2_parameter_calibration_bounded_927c5de as lazy_calibration  # noqa: E402
import c2_parameter_pair_manifest_927c5de as pair_builder  # noqa: E402
import c2_parameter_verdict_927c5de as frozen  # noqa: E402
import test_c2_parameter_inventory_927c5de as calibration_fixtures  # noqa: E402
import test_c2_parameter_verdict_927c5de as fixtures  # noqa: E402


@pytest.mark.parametrize(
    "case",
    [
        "pass",
        "breach",
        "integer",
        "missing",
        "duplicate",
        "keys",
        "shape",
        "dtype",
        "nan",
        "inf",
        "empty",
        "identity",
        "selfhash",
        "payloadhash",
        "path",
        "missing_tolerance",
        "same_arm",
        "lock",
    ],
)
def test_bounded_verdict_is_byte_identical_to_frozen(tmp_path, case):
    cal, pairs, original_out = fixtures.setup_case(tmp_path)
    on_path = tmp_path / "on-1.json"
    on = json.loads(on_path.read_text())
    pair = json.loads(pairs[0].read_text())
    if case == "breach":
        on["tensors"][0]["values"][0] = 10.0
    elif case == "integer":
        on["tensors"][1]["values"][0] = 9
    elif case == "missing":
        pair["on_inventory"] = "missing.json"
    elif case == "duplicate":
        on["tensors"].append(on["tensors"][0].copy())
    elif case == "keys":
        on["tensors"].pop()
    elif case == "shape":
        on["tensors"][0]["shape"] = [1, 2]
    elif case == "dtype":
        on["tensors"][0]["dtype"] = "float64"
    elif case in {"nan", "inf"}:
        on["tensors"][0]["values"][0] = float(case)
    elif case == "empty":
        for path in (tmp_path / "off-1.json", on_path):
            data = json.loads(path.read_text())
            data["tensors"][0].update(shape=[0], values=[])
            fixtures.write_json(path, data)
        on = json.loads(on_path.read_text())
        fixtures.refresh_pair_hash(pairs[0], "off")
        pair = json.loads(pairs[0].read_text())
    elif case == "identity":
        on["product_sha"] = "f" * 40
    elif case == "payloadhash":
        payload = tmp_path / "bad.npy"
        payload.write_bytes(b"bad")
        on["tensors"][0].pop("values")
        on["tensors"][0].update(npy=payload.name, payload_sha256="0" * 64)
    elif case == "path":
        on["tensors"][0].pop("values")
        on["tensors"][0].update(npy="../escape.npy", payload_sha256="0" * 64)
    elif case == "missing_tolerance":
        data = json.loads(cal.read_text())
        data["tensor_tolerances"].clear()
        fixtures.write_json(cal, data)
        for p in pairs:
            data = json.loads(p.read_text())
            data["calibration_sha256"] = bounded.sha256_file(cal)
            fixtures.write_json(p, data)
        pair = json.loads(pairs[0].read_text())
    elif case == "same_arm":
        pair["on_inventory"] = pair["off_inventory"]
    elif case == "lock":
        on["lock_sha256"] = "f" * 64
    fixtures.write_json(on_path, on)
    if case == "selfhash":
        on["self_sha256"] = "0" * 64
        on_path.write_text(json.dumps(on))
    pair["on_inventory_sha256"] = bounded.sha256_file(on_path)
    fixtures.write_json(pairs[0], pair)
    args = argparse.Namespace(calibration=str(cal), pair_manifest=[str(p) for p in pairs], out=str(original_out))
    old = frozen.run(args)
    args.out = str(tmp_path / "bounded.json")
    new = bounded.run(args)
    assert old == new
    assert original_out.read_bytes() == pathlib.Path(args.out).read_bytes()


def test_calibration_lazy_matches_original_builder_and_hash(tmp_path):
    identity = calibration_fixtures.identity()
    paths = {
        f"P-C{n}-off": calibration_fixtures.export(tmp_path, f"P-C{n}-off", value)
        for n, value in enumerate((1.0, 1.125, 1.0, 1.25), 1)
    }
    loaded = {arm: {"path": path, **calibration.load_inventory(path, identity, arm)} for arm, path in paths.items()}
    original = calibration.build_calibration(loaded, identity)
    new = lazy_calibration.build(paths, identity)
    assert json.dumps(original, indent=2, sort_keys=True) == json.dumps(new, indent=2, sort_keys=True)


def test_lazy_calibration_rejects_duplicate_tensor_names(tmp_path):
    path = calibration_fixtures.export(tmp_path, "P-C1-off", 1.0)
    raw = json.loads(path.read_text())
    raw["tensors"].append(raw["tensors"][0])
    fixtures.write_json(path, raw)
    with pytest.raises(frozen.InvalidError, match="duplicate"):
        bounded.Inventory(path, product_sha=raw["product_sha"], protocol_sha256=raw["protocol_sha256"])


@pytest.mark.parametrize("case", ["nan", "inf", "integer", "shape", "dtype", "keys", "missing", "payloadhash", "path"])
def test_calibration_rejects_bad_inputs_in_both_executors(tmp_path, case):
    identity = calibration_fixtures.identity()
    paths = {f"P-C{n}-off": calibration_fixtures.export(tmp_path, f"P-C{n}-off", 1.0) for n in (1, 2, 3, 4)}
    path = paths["P-C2-off"]
    raw = json.loads(path.read_text())
    tensor = next(t for t in raw["tensors"] if t["dtype"] == "bfloat16")
    if case in {"nan", "inf", "integer", "shape", "dtype", "keys"}:
        tensor.pop("npy")
        tensor.pop("payload_sha256")
        tensor["values"] = [float(case) if case in {"nan", "inf"} else 1.0, 2.0]
    if case == "integer":
        tensor["dtype"] = "int64"
    elif case == "shape":
        tensor["shape"] = [1, 2]
    elif case == "dtype":
        tensor["dtype"] = "float64"
    elif case == "keys":
        raw["tensors"].remove(tensor)
    elif case == "missing":
        tensor["npy"] = "missing.npy"
    elif case == "payloadhash":
        tensor["payload_sha256"] = "0" * 64
    elif case == "path":
        tensor["npy"] = "../escape.npy"
    fixtures.write_json(path, raw)
    with pytest.raises((ValueError, frozen.InvalidError, frozen.IncompleteError)):
        loaded = {arm: {"path": p, **calibration.load_inventory(p, identity, arm)} for arm, p in paths.items()}
        calibration.build_calibration(loaded, identity)
    with pytest.raises((ValueError, frozen.InvalidError, frozen.IncompleteError)):
        lazy_calibration.build(paths, identity)


def test_formal_measurement_does_not_bypass_runner_lineage(tmp_path, monkeypatch):
    import c2_parameter_campaign_927c5de as campaign

    cal, pairs, out = fixtures.setup_case(tmp_path)
    seen = []

    def reject(args):
        seen.append(args.campaign)
        raise ValueError("formal tensor payload hash mismatch")

    monkeypatch.setattr(campaign, "_measurement_result", reject)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bounded",
            "--lock",
            str(tmp_path / "lock.json"),
            "--campaign",
            str(tmp_path),
            "--calibration-result",
            str(cal),
            "--pair-manifest",
            str(pairs[0]),
            "--pair-manifest",
            str(pairs[1]),
            "--out",
            str(out),
        ],
    )
    assert bounded.main() == 2
    assert seen == [tmp_path]
    assert json.loads(out.read_text())["verdict"] == "INVALID"


def test_pair_two_keeps_treatment_labels_despite_ba_order(tmp_path, monkeypatch):
    cal = tmp_path / "calibration.json"
    fixtures.write_json(cal, fixtures.calibration())
    lock_path = tmp_path / "lock.json"
    lock_path.write_text("{}")
    lock = {
        "STAGE": "MEASUREMENT",
        "CALIBRATION_RESULT_SHA256": bounded.sha256_file(cal),
        "PRODUCT_SHA": fixtures.PRODUCT,
        "PROTOCOL_SHA256": fixtures.PROTOCOL,
    }
    monkeypatch.setattr(pair_builder, "load_lock", lambda _: lock)
    for n in (1, 2):
        for side in ("off", "on"):
            arm = f"P-M{n}-{side}"
            raw = fixtures.inventory(arm_name=arm)
            raw["lock_sha256"] = bounded.sha256_file(lock_path)
            fixtures.write_json(tmp_path / arm / "inventory.json", raw)
    outputs = pair_builder.build(tmp_path, cal, lock_path)
    second = json.loads(outputs[1].read_text())
    assert second["off_arm"] == "P-M2-off"
    assert second["on_arm"] == "P-M2-on"
    assert second["off_inventory"] == "P-M2-off/inventory.json"
    with pytest.raises(ValueError, match="overwrite"):
        pair_builder.build(tmp_path, cal, lock_path)
