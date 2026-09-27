# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Fail closed before submitting a campaign whose execution differs from its
lock."""

import hashlib
import json
import os
from pathlib import Path

from c2_lock import validate_lock


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def environment_digest(environment):
    # Hash values, never publish them. Ignore shell/session bookkeeping only.
    ignored = {"PWD", "OLDPWD", "SHLVL", "_"}
    values = {key: value for key, value in environment.items() if key not in ignored}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def execution_snapshot(args, overrides, runner, profile):
    return {
        "recipe_args": [a for a in (args.recipe_args or "").split(",") if a],
        "recipe_env": {"SAVE": "1", "NUM_ROLLOUT": "48", "GLOBAL_BATCH_SIZE": "32", **overrides},
        "on_profile": profile,
        "runner_sha256": digest(runner),
        "launcher_environment_sha256": environment_digest(os.environ),
        "venv": args.venv,
        "megatron": args.megatron,
        "bridge": args.bridge,
    }


def validate_execution(args, lock, *, head, dirty, overrides, runner, profile):
    validate_lock(lock)
    if head != args.head or head != lock["PRODUCT_SHA"] or dirty:
        raise ValueError("execution product differs from frozen clean product")
    recipe = args.product / "scripts/training/sft/run-qwen3-0.6B-4xgpu-dp4-observer.sh"
    if digest(recipe) != lock["RECIPE_SHA256"] or digest(args.dataset) != lock["DATASET_SHA256"]:
        raise ValueError("actual recipe or dataset differs from lock")
    execution = lock.get("EXECUTION")
    if not isinstance(execution, dict):
        raise ValueError("legacy lock lacks execution contract; create a new preregistration")
    actual = execution_snapshot(args, overrides, runner, profile)
    if execution != actual:
        differing = sorted(key for key in set(actual) | set(execution) if actual.get(key) != execution.get(key))
        raise ValueError(f"execution contract differs: {differing}")
    if str(lock["EXPECTED_STEPS"]) != actual["recipe_env"]["NUM_ROLLOUT"]:
        raise ValueError("effective step count differs from lock")
    names = [name.strip() for name in args.arms.split(",") if name.strip()]
    if names != lock["ARM_ORDER"]:
        raise ValueError("requested arms must equal frozen arm order; partial campaigns are not implicit resumes")
    return actual
