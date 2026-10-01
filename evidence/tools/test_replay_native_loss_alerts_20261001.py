# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""CPU-only input-integrity checks for the observer-only alert replay tool."""

import hashlib
import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay_native_loss_alerts_20261001 import (  # noqa: E402
    ARMS,
    PRODUCT_SHA,
    read_json,
    read_jsonl,
    replay_arm,
    resolve_input,
    validate_envelope_identities,
    validate_saved_verdicts,
    verify_job_log_hash,
    verify_profiler_job_log,
)


def test_json_object_duplicate_key_is_rejected(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text('{"arm":"L-M1-on","arm":"L-M2-on"}', encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate JSON key: arm"):
        read_json(path)


def test_jsonl_duplicate_key_is_rejected(tmp_path):
    path = tmp_path / "envelopes.jsonl"
    path.write_text('{"rank":0,"rank":1,"seq":2,"name":"forward-compute"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate JSON key: rank"):
        read_jsonl(path)


def test_duplicate_envelope_identity_is_rejected():
    envelope = {"rank": 2, "seq": 17, "name": "forward-compute"}

    with pytest.raises(ValueError, match="duplicate envelope identity"):
        validate_envelope_identities([envelope, dict(envelope)])


def test_duplicate_saved_verdict_identity_is_rejected():
    verdict = {
        "cohort": "dense:0",
        "name": "forward-compute",
        "rank": 2,
        "window_index": 17,
        "kind": "straggler",
    }

    with pytest.raises(ValueError, match="duplicate saved verdict identity"):
        validate_saved_verdicts([verdict, dict(verdict)])


@pytest.mark.parametrize(
    ("updates", "removed", "message"),
    [
        ({}, {"kind"}, "missing fields"),
        ({"cohort": 4}, set(), "cohort must be"),
        ({"name": ""}, set(), "name must be"),
        ({"rank": "2"}, set(), "rank must be"),
        ({"rank": True}, set(), "rank must be"),
        ({"window_index": 1.0}, set(), "window_index must be"),
        ({"kind": "other"}, set(), "kind is invalid"),
    ],
)
def test_saved_verdict_identity_fields_are_complete_and_typed(updates, removed, message):
    verdict = {
        "cohort": "dense:0",
        "name": "forward-compute",
        "rank": 2,
        "window_index": 17,
        "kind": "straggler",
    }
    verdict.update(updates)
    for key in removed:
        verdict.pop(key)

    with pytest.raises(ValueError, match=message):
        validate_saved_verdicts([verdict])


def test_job_log_confirms_sender_and_collector_at_five_second_window(tmp_path):
    job_log = tmp_path / "job.log"
    job_log.write_text(
        "\n".join(
            (
                "straggler profiler started: role=sender identity=rank1 collector=127.0.0.1:1234",
                "straggler profiler enabled: role=sender, log_level=2, event_pool=512, window=5.0s",
                "straggler profiler started: role=collector identity=rank0 collector=127.0.0.1:1234",
                "straggler profiler enabled: role=collector, log_level=2, event_pool=512, window=5.0s",
            )
        ),
        encoding="utf-8",
    )

    result = verify_profiler_job_log(job_log)

    assert result == {
        "started_roles": ["collector", "sender"],
        "enabled_roles": ["collector", "sender"],
        "window_seconds_by_role": {"sender": ["5.0"], "collector": ["5.0"]},
    }


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        (
            [
                "straggler profiler started: role=sender",
                "straggler profiler enabled: role=sender, window=5.0s",
                "straggler profiler enabled: role=collector, window=5.0s",
            ],
            "missing straggler profiler started roles",
        ),
        (
            [
                "straggler profiler started: role=sender",
                "straggler profiler started: role=collector",
                "straggler profiler enabled: role=sender, window=5.0s",
            ],
            "missing straggler profiler enabled role=collector",
        ),
        (
            [
                "straggler profiler started: role=sender",
                "straggler profiler started: role=collector",
                "straggler profiler enabled: role=sender, window=5.0s",
                "straggler profiler enabled: role=collector, window=10.0s",
            ],
            "unexpected profiler window for role=collector",
        ),
    ],
)
def test_job_log_rejects_missing_or_wrong_profiler_configuration(tmp_path, lines, message):
    job_log = tmp_path / "job.log"
    job_log.write_text("\n".join(lines), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        verify_profiler_job_log(job_log)


def test_job_log_hash_mismatch_is_rejected_after_tampering(tmp_path):
    job_log = tmp_path / "job.log"
    job_log.write_text("original log bytes\n", encoding="utf-8")
    frozen_hash = hashlib.sha256(job_log.read_bytes()).hexdigest()
    job_log.write_text("modified log bytes\n", encoding="utf-8")

    with pytest.raises(ValueError, match="job.log SHA-256 mismatch"):
        verify_job_log_hash(job_log, frozen_hash)


@pytest.mark.parametrize("expected_hash", [None, "", "not-a-hash", "A" * 64])
def test_missing_or_malformed_job_log_hash_is_rejected(tmp_path, expected_hash):
    job_log = tmp_path / "job.log"
    job_log.write_text("log bytes\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing or invalid job_log_sha256"):
        verify_job_log_hash(job_log, expected_hash)


def test_symlink_escape_from_measurement_root_is_rejected(tmp_path):
    root = tmp_path / "measurement"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "manifest.json").write_text("{}", encoding="utf-8")
    (root / "L-M1-on").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="escapes measurement root"):
        resolve_input(root, Path("L-M1-on/manifest.json"))


def test_replay_rejects_run_directory_symlink_escape(tmp_path):
    root = tmp_path / "measurement"
    arm_root = root / "L-M1-on" / "straggler"
    outside = tmp_path / "outside"
    arm_root.mkdir(parents=True)
    outside.mkdir()
    (outside / "sentinel").write_text("outside", encoding="utf-8")
    (arm_root / ARMS["L-M1-on"]).symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="escapes measurement root"):
        replay_arm("L-M1-on", root, object, object)


def test_replay_checks_manifest_job_log_hash_before_detector(tmp_path):
    root = tmp_path / "measurement"
    arm_root = root / "L-M1-on"
    run_dir = arm_root / "straggler" / ARMS["L-M1-on"]
    run_dir.mkdir(parents=True)
    (arm_root / "job.log").write_text("tampered", encoding="utf-8")
    manifest = {
        "product_sha": PRODUCT_SHA,
        "arm": "L-M1-on",
        "status": "SUCCEEDED",
        "valid": True,
        "job_log_sha256": "0" * 64,
        "launch_spec": {"observer": {"RELAX_STRAGGLER_ENABLE": "1"}},
    }
    (arm_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "straggler_envelopes.jsonl").write_text("", encoding="utf-8")
    (run_dir / "straggler_verdicts.jsonl").write_text("", encoding="utf-8")
    (run_dir / "collector_status.json").write_text("{}", encoding="utf-8")
    (run_dir / "runtime_status.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="job.log SHA-256 mismatch"):
        replay_arm("L-M1-on", root, object, object)


def test_valid_job_log_hash_and_in_root_file_are_accepted(tmp_path):
    root = tmp_path / "measurement"
    arm = root / "L-M1-on"
    arm.mkdir(parents=True)
    job_log = arm / "job.log"
    job_log.write_text("frozen log bytes\n", encoding="utf-8")
    expected_hash = hashlib.sha256(job_log.read_bytes()).hexdigest()

    assert verify_job_log_hash(job_log, expected_hash) == expected_hash
    assert resolve_input(root, Path("L-M1-on/job.log")) == job_log.resolve()
