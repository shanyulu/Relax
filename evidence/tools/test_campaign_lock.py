#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Adversarial tests for campaign_lock.validate: every corrupt manifest fails.

Twelve synthetic corruptions, one per hardening requirement: recipe hash drift,
product SHA drift, dirty tree, wrong env fingerprint, wrong expected steps,
wrong pair order, wrong analyzer, wrong runner, wrong protocol, wrong lock
hash, ON env drift, and a missing required field. Plus one golden manifest that
must validate. Run: python -m pytest test_campaign_lock.py -q
"""

import copy
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys


HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))


TMP = pathlib.Path("/tmp/opencode/campaign_lock_tests")

LOCK = {
    "PRODUCT_SHA": "a" * 40,
    "PR_HEAD": "a" * 40,
    "ANALYZER_SHA": "b" * 64,
    "RUNNER_SHA": "c" * 64,
    "PROTOCOL_SHA": "d" * 64,
    "RECIPE_PATH": "/repo/scripts/training/sft/run-observer.sh",
    "RECIPE_SHA256": "e" * 64,
    "DATASET_PATH": "/repo/data.jsonl",
    "DATASET_SHA256": "f" * 64,
    "ENV_FINGERPRINT_SHA256": "9" * 64,
    "EXPECTED_STEPS": 48,
    "PAIR_ORDER": ["S7-off", "S7-on", "S8-on", "S8-off"],
    "BOOTSTRAP_SEED": 20260926,
    "PRIMARY_METRIC": "perf/train_time",
    "ACCEPTANCE_RULE": "PASS iff ...",
    "TRACE_BACKEND": "torch.profiler(Kineto/CUPTI)",
    "C2_TOLERANCES": "two-stage: see C2 calibration/measurement locks",
    "ON_ARM_PROFILE": {
        "RELAX_STRAGGLER_ENABLE": "1",
        "RELAX_STRAGGLER_WINDOW_S": "5",
    },
}

GOLDEN_MANIFEST = {
    "run_id": "S7-off",
    "session": "S7",
    "arm": "off",
    "order": "A->B",
    "pr_head": "a" * 40,
    "git": {"commit": "a" * 40, "dirty": False},
    "dataset_sha256": "f" * 64,
    "recipe": "/repo/scripts/training/sft/run-observer.sh",
    "recipe_sha256": "e" * 64,
    "env_fingerprint_sha256": "9" * 64,
    "expected_steps": 48,
    "analyzer_sha256": "b" * 64,
    "runner_sha256": "c" * 64,
    "protocol_sha256": "d" * 64,
    "lock_sha256": None,  # filled per case
    "relax_env": {},
}


def build_case(name, mutate_manifest=None, mutate_lock=None):
    root = TMP / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    lock = copy.deepcopy(LOCK)
    if mutate_lock:
        mutate_lock(lock)
    lock_file = root / "CAMPAIGN_LOCK.json"
    lock_file.write_text(json.dumps(lock, indent=2) + "\n")
    manifest = copy.deepcopy(GOLDEN_MANIFEST)
    manifest["lock_sha256"] = hashlib.sha256(lock_file.read_bytes()).hexdigest()
    if mutate_manifest:
        mutate_manifest(manifest)
    arm_dir = root / "S7-off"
    arm_dir.mkdir()
    (arm_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return str(lock_file), str(arm_dir)


def run_validate(lock_path, arm_dir):
    result = subprocess.run(
        [sys.executable, str(HERE / "campaign_lock.py"), "validate", "--lock", lock_path, "--arm", arm_dir],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout + result.stderr


def test_golden_manifest_validates():
    lock_path, arm_dir = build_case("golden")
    code, out = run_validate(lock_path, arm_dir)
    assert code == 0, out


def test_recipe_hash_drift_is_invalid():
    def mutate(m):
        m["recipe_sha256"] = "0" * 64

    code, out = run_validate(*build_case("recipe_drift", mutate))
    assert code == 1 and "recipe sha drift" in out


def test_recipe_path_drift_is_invalid():
    def mutate(m):
        m["recipe"] = "/other/recipe.sh"

    code, out = run_validate(*build_case("recipe_path_drift", mutate))
    assert code == 1 and "recipe path drift" in out


def test_product_sha_drift_is_invalid():
    def mutate(m):
        m["git"]["commit"] = "b" * 40

    code, out = run_validate(*build_case("product_drift", mutate))
    assert code == 1 and "product sha" in out


def test_dirty_tree_is_invalid():
    def mutate(m):
        m["git"]["dirty"] = True

    code, out = run_validate(*build_case("dirty_tree", mutate))
    assert code == 1 and "dirty" in out


def test_wrong_env_fingerprint_is_invalid():
    def mutate(m):
        m["env_fingerprint_sha256"] = "1" * 64

    code, out = run_validate(*build_case("env_drift", mutate))
    assert code == 1 and "env fingerprint drift" in out


def test_wrong_expected_steps_is_invalid():
    def mutate(m):
        m["expected_steps"] = 47

    code, out = run_validate(*build_case("steps_drift", mutate))
    assert code == 1 and "expected steps" in out


def test_wrong_pair_order_is_invalid():
    def mutate(m):
        m["session"] = "S99"
        m["run_id"] = "S99-off"

    code, out = run_validate(*build_case("pair_drift", mutate))
    assert code == 1 and "not in locked PAIR_ORDER" in out


def test_wrong_analyzer_is_invalid():
    def mutate(m):
        m["analyzer_sha256"] = "2" * 64

    code, out = run_validate(*build_case("analyzer_drift", mutate))
    assert code == 1 and "analyzer_sha256 drift" in out


def test_wrong_runner_is_invalid():
    def mutate(m):
        m["runner_sha256"] = "3" * 64

    code, out = run_validate(*build_case("runner_drift", mutate))
    assert code == 1 and "runner_sha256 drift" in out


def test_wrong_protocol_is_invalid():
    def mutate(m):
        m["protocol_sha256"] = "4" * 64

    code, out = run_validate(*build_case("protocol_drift", mutate))
    assert code == 1 and "protocol_sha256 drift" in out


def test_wrong_lock_hash_is_invalid():
    def mutate(m):
        m["lock_sha256"] = "5" * 64

    code, out = run_validate(*build_case("lock_drift", mutate))
    assert code == 1 and "lock_sha256 mismatch" in out


def test_on_arm_env_drift_is_invalid():
    def mutate(m):
        m["arm"] = "on"
        m["run_id"] = "S7-on"
        m["relax_env"] = {"RELAX_STRAGGLER_ENABLE": "1", "RELAX_STRAGGLER_WINDOW_S": "9"}

    code, out = run_validate(*build_case("on_env_drift", mutate))
    assert code == 1 and "ON-arm env drift" in out


def test_off_arm_with_enabled_straggler_env_is_invalid():
    def mutate(m):
        m["relax_env"] = {"RELAX_STRAGGLER_ENABLE": "1"}

    code, out = run_validate(*build_case("off_env_leak", mutate))
    assert code == 1 and "OFF arm has straggler env set" in out


def test_missing_required_field_in_manifest_is_invalid():
    def mutate(m):
        del m["dataset_sha256"]

    code, out = run_validate(*build_case("missing_field", mutate))
    assert code == 1 and "dataset sha drift" in out


def test_incomplete_lock_is_invalid():
    def mutate_lock(lock):
        del lock["BOOTSTRAP_SEED"]

    code, out = run_validate(*build_case("incomplete_lock", mutate_lock=mutate_lock))
    assert code == 1 and "lock itself incomplete" in out


def test_pr_head_drift_is_invalid():
    def mutate(m):
        m["pr_head"] = "c" * 40

    code, out = run_validate(*build_case("pr_head_drift", mutate))
    assert code == 1 and "producing head" in out
