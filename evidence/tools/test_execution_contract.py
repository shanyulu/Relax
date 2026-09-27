# Copyright (c) 2026 Relax Authors. All Rights Reserved.

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from execution_contract import digest, environment_digest, validate_execution
from test_acceptance_cli import base_lock, seal


def test_freeze_execution_never_submits_ray_job(tmp_path, monkeypatch):
    import run_c2_campaign as runner

    recipe = tmp_path / "scripts/training/sft/run-qwen3-0.6B-4xgpu-dp4-observer.sh"
    recipe.parent.mkdir(parents=True)
    recipe.write_text("recipe")
    dataset = tmp_path / "data"
    dataset.write_text("data")
    lock = base_lock()
    lock.update(RECIPE_SHA256=digest(recipe), DATASET_SHA256=digest(dataset))
    lock_path = tmp_path / "base.json"
    lock_path.write_text(json.dumps(seal(lock)))
    frozen = tmp_path / "frozen.json"
    monkeypatch.setattr(runner, "DATASET_SHA", digest(dataset))
    monkeypatch.setattr(runner, "git", lambda root, *args: "a" * 40 if args[0] == "rev-parse" else "")

    def forbidden(*args):
        raise AssertionError("freeze must not submit or touch the cluster")

    monkeypatch.setattr(runner, "run_arm", forbidden)
    monkeypatch.setattr(runner, "preflight", forbidden)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--product",
            str(tmp_path),
            "--dataset",
            str(dataset),
            "--out",
            str(tmp_path / "campaign"),
            "--head",
            "a" * 40,
            "--dashboard",
            "unused",
            "--gcs",
            "unused",
            "--venv",
            "venv",
            "--megatron",
            "megatron",
            "--bridge",
            "bridge",
            "--gpulock",
            str(tmp_path / "gpu.lock"),
            "--lock",
            str(lock_path),
            "--arms",
            "C2M1-off,C2M1-on",
            "--freeze-execution",
            str(frozen),
        ],
    )
    runner.main()
    assert json.loads(frozen.read_text())["EXECUTION"]["recipe_env"]["NUM_ROLLOUT"] == "48"
    assert not (tmp_path / "campaign").exists()
    assert not (tmp_path / "gpu.lock").exists()


@pytest.mark.parametrize("drift", [None, "recipe", "head", "order", "steps", "env", "legacy", "dirty"])
def test_execution_gate_before_submission(tmp_path, drift):
    recipe = tmp_path / "scripts/training/sft/run-qwen3-0.6B-4xgpu-dp4-observer.sh"
    recipe.parent.mkdir(parents=True)
    recipe.write_text("original recipe")
    dataset = tmp_path / "dataset"
    dataset.write_text("data")
    args = SimpleNamespace(
        product=tmp_path,
        head="a" * 40,
        dataset=dataset,
        recipe_args="",
        arms="C2M1-off,C2M1-on",
        venv="venv",
        megatron="megatron",
        bridge="bridge",
    )
    runner = Path(__file__)
    lock = base_lock()
    lock.update(RECIPE_SHA256=digest(recipe), DATASET_SHA256=digest(dataset))
    lock["EXECUTION"] = {
        "recipe_args": [],
        "recipe_env": {"SAVE": "1", "NUM_ROLLOUT": "48", "GLOBAL_BATCH_SIZE": "32"},
        "on_profile": {},
        "runner_sha256": digest(runner),
        "launcher_environment_sha256": environment_digest(os.environ),
        "venv": "venv",
        "megatron": "megatron",
        "bridge": "bridge",
    }
    if drift == "recipe":
        recipe.write_text("different recipe")
    if drift == "head":
        args.head = "b" * 40
    if drift == "order":
        args.arms = "C2M1-on,C2M1-off"
    if drift == "steps":
        lock["EXPECTED_STEPS"] = 47
    if drift == "env":
        lock["EXECUTION"]["launcher_environment_sha256"] = "0" * 64
    if drift == "legacy":
        del lock["EXECUTION"]
    seal(lock)

    def check():
        return validate_execution(
            args, lock, head="a" * 40, dirty=drift == "dirty", overrides={}, runner=runner, profile={}
        )

    if drift is None:
        assert check() == lock["EXECUTION"]
    else:
        with pytest.raises(ValueError):
            check()
