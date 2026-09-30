#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Lock, supervise and compare a loss-only Task 11 campaign.

This runner is deliberately separate from the SAVE=1 parameter campaign. It
retains job logs and manifests but does not write or require checkpoints.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import itertools
import json
import math
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from extract_c2_native import parse_arm


PRODUCT_SHA = "927c5de2f5a8f307cad0c87f2c7eb2b78262334d"
STEPS = 48
SEED = 1234
GBS = 32
CALIBRATION_ARMS = [f"L-C{i}-off" for i in range(1, 5)]
MEASUREMENT_ARMS = ["L-M1-off", "L-M1-on", "L-M2-on", "L-M2-off"]
ON_PROFILE = {
    "RELAX_STRAGGLER_ENABLE": "1",
    "RELAX_STRAGGLER_WINDOW_S": "5",
    "RELAX_STRAGGLER_WARMUP_WINDOWS": "2",
    "RELAX_STRAGGLER_REPORT_INTERVAL_S": "10",
}
EVIDENCE_REL = Path("evidence")
PROTOCOL_REL = Path("evidence/NATIVE_LOSS_PROTOCOL_927C5DE_20260930.md")
EXTRACTOR_REL = Path("evidence/tools/extract_c2_native.py")
RECIPE_REL = Path("scripts/training/sft/run-qwen3-0.6B-4xgpu-dp4-observer.sh")
DATASET_DEFAULT = Path("/root/autodl-tmp/task11-3090/preflight/dapo-math-17k-sft-256.jsonl")
ENV_DEFAULT = Path("evidence/gpu_campaign/task11_3090/ENV_FINGERPRINT.json")
CAMPAIGN_ROOT = Path("/root/autodl-tmp/task11-3090/formal/native-loss-927c5de-20260930")
TRAIN_VENV = "/root/autodl-tmp/megatron-stack/venv"
MEGATRON_PATH = "/root/autodl-tmp/megatron-stack/Megatron-LM"
BRIDGE_PATH = "/root/autodl-tmp/megatron-stack/Megatron-Bridge"
SHARED_GPU_LOCK = Path("/root/autodl-tmp/relax-ray-gpu.lock")
MODEL_PATH = (
    "/root/autodl-tmp/hf-cache/hub/models--Qwen--Qwen3-0.6B/snapshots/c1899de289a04d12100db370d81485cdf75e47ca"
)
MODEL_CONFIG_PATH = "scripts/models/qwen3-0.6B.sh"
CALIBRATION_RUNNER_COMMIT = "0220899"
RUNNER_REL = Path("evidence/tools/native_loss_campaign_927c5de.py")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_sha256(root: Path, suffixes: set[str] | None = None) -> str:
    root = root.resolve(strict=True)
    digest = hashlib.sha256()
    files = sorted(
        path for path in root.rglob("*") if path.is_file() and (suffixes is None or path.suffix in suffixes)
    )
    if not files:
        raise ValueError(f"no files found under {root}")
    for path in files:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def pip_freeze_sha256(venv: Path) -> str:
    output = subprocess.check_output([str(venv / "bin/python"), "-m", "pip", "freeze"], text=True)
    return hashlib.sha256(output.encode()).hexdigest()


def host_environment_sha256() -> str:
    names = ("PATH", "HOME", "LD_LIBRARY_PATH", "LANG", "LC_ALL", "TERM", "CUDA_HOME")
    values = {name: os.environ.get(name) for name in names}
    payload = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def discover_gcs_address() -> str:
    from ray._private.services import get_node_ip_address

    node_ip = get_node_ip_address()
    with socket.create_connection((node_ip, 6379), timeout=3):
        pass
    return f"{node_ip}:6379"


def canonical_sha(value: dict[str, Any]) -> str:
    payload = {**value, "_self_sha256": None}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def write_once(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as output:
        json.dump(payload, output, indent=2, sort_keys=True, allow_nan=False)
        output.write("\n")


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def committed(root: Path, path: Path, expected_sha: str | None = None) -> str:
    rel = path.resolve().relative_to(root.resolve()).as_posix()
    if git(root, "ls-files", "--error-unmatch", rel) == "":
        raise ValueError(f"file is not tracked: {rel}")
    blob = git(root, "rev-parse", f"HEAD:{rel}")
    working = git(root, "hash-object", rel)
    if blob != working:
        raise ValueError(f"committed file differs from worktree: {rel}")
    commit = git(root, "log", "-1", "--format=%H", "HEAD", "--", rel)
    if not commit:
        raise ValueError(f"file has no committed history: {rel}")
    if expected_sha and sha256(path) != expected_sha:
        raise ValueError(f"file hash differs from lock: {rel}")
    return commit


def historical_file_sha256(root: Path, commit: str, relpath: Path) -> str:
    payload = subprocess.check_output(["git", "-C", str(root), "show", f"{commit}:{relpath.as_posix()}"])
    return hashlib.sha256(payload).hexdigest()


def product_preflight(product: Path) -> None:
    if git(product, "rev-parse", "HEAD") != PRODUCT_SHA:
        raise ValueError("product checkout is not the locked 927c5de")
    if git(product, "status", "--porcelain"):
        raise ValueError("product checkout is dirty")


def source_fingerprint(relax_root: Path) -> str:
    digest = hashlib.sha256()
    files = sorted((relax_root.parent / "relax/utils/straggler").glob("*.py"))
    if not files:
        raise ValueError(f"missing straggler sources for {relax_root}")
    for path in files:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def create_calibration_lock(args: argparse.Namespace) -> dict[str, Any]:
    repo, product = args.repo.resolve(), args.product.resolve()
    product_preflight(product)
    protocol = repo / PROTOCOL_REL
    runner = Path(__file__).resolve()
    extractor = repo / EXTRACTOR_REL
    recipe = product / RECIPE_REL
    dataset, env = args.dataset.resolve(), args.env_fingerprint.resolve()
    for path in (protocol, runner, extractor, recipe, dataset, env):
        if not path.is_file():
            raise ValueError(f"missing locked input: {path}")
    committed(repo, env)
    fingerprint = json.loads(env.read_text())
    if fingerprint.get("product_sha") != PRODUCT_SHA or fingerprint.get("dataset_sha256") != sha256(dataset):
        raise ValueError("environment fingerprint does not match product/dataset")
    gcs_address = discover_gcs_address()
    addresses = json.dumps([args.dashboard, gcs_address], separators=(",", ":")).encode()
    if args.dashboard != "http://127.0.0.1:8265" or args.gcs != "auto":
        raise ValueError("Ray endpoints do not match the inspected local cluster")
    lock = {
        "schema": "TASK11_NATIVE_LOSS_CAMPAIGN/v1",
        "stage": "CALIBRATION",
        "product_sha": PRODUCT_SHA,
        "recipe_sha256": sha256(recipe),
        "recipe_relpath": RECIPE_REL.as_posix(),
        "dataset_sha256": sha256(dataset),
        "dataset_path": str(dataset),
        "environment_fingerprint_sha256": sha256(env),
        "protocol_sha256": sha256(protocol),
        "runner_sha256": sha256(runner),
        "extractor_sha256": sha256(extractor),
        "straggler_source_sha256": source_fingerprint(product / "relax"),
        "dashboard_gcs_sha256": hashlib.sha256(addresses).hexdigest(),
        "host_environment_sha256": host_environment_sha256(),
        "training_paths_sha256": hashlib.sha256(
            json.dumps([TRAIN_VENV, MEGATRON_PATH, BRIDGE_PATH], separators=(",", ":")).encode()
        ).hexdigest(),
        "runtime": {
            "model_path": MODEL_PATH,
            "model_tree_sha256": tree_sha256(Path(MODEL_PATH)),
            "model_config_relpath": MODEL_CONFIG_PATH,
            "model_config_sha256": sha256(product / MODEL_CONFIG_PATH),
            "training_venv": TRAIN_VENV,
            "training_venv_python": subprocess.check_output(
                [f"{TRAIN_VENV}/bin/python", "--version"], text=True, stderr=subprocess.STDOUT
            ).strip(),
            "training_pip_freeze_sha256": pip_freeze_sha256(Path(TRAIN_VENV)),
            "megatron_python_tree_sha256": tree_sha256(Path(MEGATRON_PATH), {".py"}),
            "bridge_python_tree_sha256": tree_sha256(Path(BRIDGE_PATH), {".py"}),
            "num_gpus": 4,
            "save": 0,
        },
        "topology": {"gpu": "4xRTX3090", "tp": 1, "dp": 4, "pp": 1, "gbs": GBS},
        "steps": STEPS,
        "seed": SEED,
        "save": 0,
        "on_profile": ON_PROFILE,
        "arm_order": CALIBRATION_ARMS,
        "calibration_rule": "2*max_abs_step_delta_over_all_6_pairwise_OFF_contrasts_separately_for_loss_and_grad_norm",
        "_self_sha256": None,
    }
    lock["_self_sha256"] = canonical_sha(lock)
    return lock


def validate_lock(repo: Path, lock_path: Path, stage: str) -> dict[str, Any]:
    committed(repo, lock_path)
    lock = json.loads(lock_path.read_text())
    if not isinstance(lock, dict) or lock.get("schema") != "TASK11_NATIVE_LOSS_CAMPAIGN/v1":
        raise ValueError("invalid campaign lock")
    if lock.get("_self_sha256") != canonical_sha(lock):
        raise ValueError("campaign lock self-hash mismatch")
    if lock.get("stage") != stage or lock.get("product_sha") != PRODUCT_SHA:
        raise ValueError("campaign stage/product mismatch")
    if stage == "MEASUREMENT":
        committed(repo, Path(__file__), lock.get("measurement_runner_sha256"))
    try:
        committed(repo, repo / RUNNER_REL, lock.get("runner_sha256"))
    except ValueError:
        historic_sha = historical_file_sha256(repo, CALIBRATION_RUNNER_COMMIT, RUNNER_REL)
        if lock.get("runner_sha256") != historic_sha:
            raise
    committed(repo, repo / EXTRACTOR_REL, lock.get("extractor_sha256"))
    committed(repo, repo / PROTOCOL_REL, lock.get("protocol_sha256"))
    if stage == "MEASUREMENT":
        calibration_lock_path = Path(lock.get("calibration_lock_path", ""))
        calibration_lock = validate_lock(repo, calibration_lock_path, "CALIBRATION")
        if calibration_lock.get("_self_sha256") != lock.get("calibration_lock_sha256"):
            raise ValueError("measurement lock calibration-lock reference mismatch")
        calibration_path = Path(lock.get("calibration_result_path", ""))
        calibration_commit = committed(repo, calibration_path, lock.get("calibration_result_sha256"))
        if calibration_commit != lock.get("calibration_result_commit"):
            raise ValueError("measurement lock calibration-result commit mismatch")
        result = json.loads(calibration_path.read_text())
        if result.get("_self_sha256") != canonical_sha(result):
            raise ValueError("calibration result self-hash mismatch")
        if (
            result.get("lock_sha256") != calibration_lock.get("_self_sha256")
            or result.get("product_sha") != PRODUCT_SHA
        ):
            raise ValueError("calibration result does not belong to the locked product/calibration lock")
        if list(result.get("arm_manifests", {})) != CALIBRATION_ARMS:
            raise ValueError("calibration result does not contain the four frozen OFF arms")
        for field in ("loss_series", "grad_norm_series"):
            try:
                maxima = [item[field]["max_abs_delta"] for item in result["contrasts"]]
                tolerance = result["tolerances"][field]
            except (KeyError, TypeError) as exc:
                raise ValueError("calibration result is missing contrast/tolerance data") from exc
            if len(maxima) != 6 or any(
                isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0
                for value in maxima
            ):
                raise ValueError(f"calibration result has invalid contrast values for {field}")
            if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or not math.isfinite(tolerance):
                raise ValueError(f"calibration result has invalid tolerance for {field}")
            if tolerance != 2.0 * max(maxima):
                raise ValueError(f"calibration tolerance formula mismatch for {field}")
    return lock


def validate_arm(arm_dir: Path, lock: dict[str, Any], name: str, job_log: Path) -> dict[str, Any]:
    manifest_path = arm_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("_self_sha256") != canonical_sha(manifest):
        raise ValueError(f"{name}: manifest self-hash mismatch")
    if manifest.get("arm") != name or manifest.get("lock_sha256") != lock["_self_sha256"]:
        raise ValueError(f"{name}: arm/lock identity mismatch")
    for field in ("product_sha", "recipe_sha256", "dataset_sha256", "environment_fingerprint_sha256"):
        expected = {
            "product_sha": PRODUCT_SHA,
            "recipe_sha256": lock["recipe_sha256"],
            "dataset_sha256": lock["dataset_sha256"],
            "environment_fingerprint_sha256": lock["environment_fingerprint_sha256"],
        }[field]
        if manifest.get(field) != expected:
            raise ValueError(f"{name}: {field} mismatch")
    if (
        manifest.get("status") != "SUCCEEDED"
        or manifest.get("resources_returned") is not True
        or manifest.get("valid") is not True
        or manifest.get("save_flag_absent") is not True
    ):
        raise ValueError(f"{name}: job failed or resources not returned")
    if manifest.get("save") != 0 or manifest.get("checkpoint_directory_created"):
        raise ValueError(f"{name}: SAVE=0 invariant violated")
    if sha256(job_log) != manifest.get("job_log_sha256"):
        raise ValueError(f"{name}: job log hash mismatch")
    roots = manifest.get("worker_source_roots")
    source_hashes = manifest.get("worker_source_sha256")
    if not roots or not isinstance(source_hashes, dict) or set(roots) != set(source_hashes):
        raise ValueError(f"{name}: worker source provenance is missing or incomplete")
    for root in roots:
        actual_source_hash = source_fingerprint(Path(root))
        if source_hashes[root] != actual_source_hash or actual_source_hash != lock["straggler_source_sha256"]:
            raise ValueError(f"{name}: worker sources differ from locked product")
    argv_path = arm_dir / "train-argv.nul"
    if not argv_path.is_file() or sha256(argv_path) != manifest.get("resolved_argv_sha256"):
        raise ValueError(f"{name}: resolved launch argv is missing or changed")
    argv = [value.decode() for value in argv_path.read_bytes().split(b"\0") if value]
    if "--save" in argv or "--save-interval" in argv or "--seed" not in argv:
        raise ValueError(f"{name}: resolved argv violates SAVE=0 or seed contract")
    parsed = parse_arm(arm_dir, expected_steps=STEPS)
    if not parsed.get("native_valid"):
        raise ValueError(f"{name}: invalid native metrics: {parsed.get('extraction_errors')}")
    try:
        argv = validate_resolved_argv(argv_path.read_bytes())
    except ValueError as exc:
        raise ValueError(f"{name}: invalid resolved launch argv: {exc}") from exc
    parsed["resolved_argv_sha256"] = manifest["resolved_argv_sha256"]
    parsed["normalized_argv_sha256"] = normalized_argv_sha256(argv)
    return parsed


def _max_delta(left: list[float], right: list[float]) -> tuple[float, int]:
    if len(left) != STEPS or len(right) != STEPS:
        raise ValueError("each series must contain exactly 48 steps")
    deltas = [(abs(b - a), i) for i, (a, b) in enumerate(zip(left, right))]
    maximum, step = max(deltas)
    return maximum, step


def validate_resolved_argv(payload: bytes, seed: int = SEED) -> list[str]:
    argv = [value.decode() for value in payload.split(b"\0") if value]
    if "--save" in argv or "--save-interval" in argv or "--seed" not in argv:
        raise ValueError("resolved argv violates SAVE=0 or explicit-seed contract")
    index = argv.index("--seed")
    if argv[index + 1 : index + 2] != [str(seed)]:
        raise ValueError("resolved argv does not use the frozen seed")
    return argv


def normalized_argv_sha256(argv: list[str]) -> str:
    normalized: list[str] = []
    index = 0
    while index < len(argv):
        value = argv[index]
        normalized.append(value)
        if value == "--tb-experiment-name":
            if index + 1 >= len(argv):
                raise ValueError("TensorBoard experiment-name flag has no value")
            normalized.append("<per-arm-tensorboard-name>")
            index += 2
            continue
        index += 1
    return hashlib.sha256(json.dumps(normalized, separators=(",", ":")).encode()).hexdigest()


def compare_pair(a: dict[str, Any], b: dict[str, Any], tolerances: dict[str, float]) -> dict[str, Any]:
    gates = {
        "step_ids_equal": a["native_step_ids"] == b["native_step_ids"],
        "token_volume_equal": a["token_series"] == b["token_series"],
        "learning_rate_equal": a["learning_rate_series"] == b["learning_rate_series"],
        "updates_equal": a["update_count"] == b["update_count"] == STEPS,
        "resolved_argv_equal": a["normalized_argv_sha256"] == b["normalized_argv_sha256"],
    }
    metrics = {}
    for field in ("loss_series", "grad_norm_series"):
        delta, step = _max_delta(a[field], b[field])
        tolerance = tolerances[field]
        metrics[field] = {
            "max_abs_delta": delta,
            "step": step,
            "tolerance": tolerance,
            "within_envelope": delta <= tolerance,
        }
    eligible = all(gates.values())
    passed = eligible and all(value["within_envelope"] for value in metrics.values())
    return {
        "gates": gates,
        "eligible": eligible,
        "status": "PASS" if passed else ("NOT_PASS" if eligible else "INVALID"),
        "metrics": metrics,
        "pass": passed,
    }


def calibration_result(lock: dict[str, Any], arm_series: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if list(arm_series) != lock["arm_order"]:
        raise ValueError("calibration arms must be complete and in frozen order")
    contrasts: list[dict[str, Any]] = []
    for left, right in itertools.combinations(lock["arm_order"], 2):
        cells = {"pair": [left, right]}
        for key in ("loss_series", "grad_norm_series"):
            value, step = _max_delta(arm_series[left][key], arm_series[right][key])
            cells[key] = {"max_abs_delta": value, "step": step}
        contrasts.append(cells)
    tolerances = {
        key: 2.0 * max(item[key]["max_abs_delta"] for item in contrasts) for key in ("loss_series", "grad_norm_series")
    }
    result = {
        "schema": "TASK11_NATIVE_LOSS_CALIBRATION_RESULT/v1",
        "product_sha": PRODUCT_SHA,
        "lock_sha256": lock["_self_sha256"],
        "arm_manifests": {name: arm_series[name]["manifest_sha256"] for name in lock["arm_order"]},
        "raw_argv_sha256": {name: arm_series[name]["resolved_argv_sha256"] for name in lock["arm_order"]},
        "normalized_argv_sha256": arm_series[lock["arm_order"][0]]["normalized_argv_sha256"],
        "contrasts": contrasts,
        "tolerances": tolerances,
        "statistical_limit": "Six pairwise contrasts share four arms; envelope only, not CI or independent samples.",
        "_self_sha256": None,
    }
    result["_self_sha256"] = canonical_sha(result)
    return result


def command_freeze_calibration(args: argparse.Namespace) -> None:
    repo = args.repo.resolve()
    lock_path = args.lock.resolve()
    lock = validate_lock(repo, lock_path, "CALIBRATION")
    if lock.get("arm_order") != CALIBRATION_ARMS:
        raise ValueError("calibration order differs from preregistration")
    root = args.campaign.resolve()
    arm_series: dict[str, dict[str, Any]] = {}
    for name in lock["arm_order"]:
        arm_dir = root / name
        arm_series[name] = validate_arm(arm_dir, lock, name, arm_dir / "job.log")
        arm_series[name]["manifest_sha256"] = sha256(arm_dir / "manifest.json")
    if len({value["normalized_argv_sha256"] for value in arm_series.values()}) != 1:
        raise ValueError("calibration OFF arms differ beyond per-arm TensorBoard naming")
    result = calibration_result(lock, arm_series)
    result["lock_path"] = str(lock_path)
    result["_self_sha256"] = canonical_sha(result)
    write_once(args.out, result)


def command_create_lock(args: argparse.Namespace) -> None:
    repo = args.repo.resolve()
    protocol = repo / PROTOCOL_REL
    runner = Path(__file__).resolve()
    extractor = repo / EXTRACTOR_REL
    for path in (protocol, runner, extractor):
        committed(repo, path)
    lock = create_calibration_lock(args)
    write_once(args.out, lock)


def command_create_measurement_lock(args: argparse.Namespace) -> None:
    repo = args.repo.resolve()
    calibration = args.calibration_result.resolve()
    calibration_commit = committed(repo, calibration)
    result = json.loads(calibration.read_text())
    if result.get("schema") != "TASK11_NATIVE_LOSS_CALIBRATION_RESULT/v1":
        raise ValueError("invalid calibration result")
    if result.get("_self_sha256") != canonical_sha(result):
        raise ValueError("calibration self-hash mismatch")
    base_path = Path(result["lock_path"])
    base = validate_lock(repo, base_path, "CALIBRATION")
    expected_names = CALIBRATION_ARMS
    expected_pairs = [{"pair": [left, right]} for left, right in itertools.combinations(expected_names, 2)]
    contrasts = result.get("contrasts")
    if (
        result.get("product_sha") != PRODUCT_SHA
        or result.get("lock_sha256") != base.get("_self_sha256")
        or list(result.get("arm_manifests", {})) != expected_names
        or not isinstance(contrasts, list)
        or [item.get("pair") for item in contrasts if isinstance(item, dict)]
        != [item["pair"] for item in expected_pairs]
    ):
        raise ValueError("calibration result identity or arm inventory mismatch")
    for field in ("loss_series", "grad_norm_series"):
        maxima = [item[field].get("max_abs_delta") for item in contrasts]
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0
            for value in maxima
        ):
            raise ValueError(f"invalid calibration contrast values for {field}")
        expected_tolerance = 2.0 * max(maxima)
        if result.get("tolerances", {}).get(field) != expected_tolerance:
            raise ValueError(f"calibration tolerance does not match frozen formula for {field}")
    if set(result.get("tolerances", {})) != {"loss_series", "grad_norm_series"}:
        raise ValueError("calibration tolerance fields are incomplete or unexpected")
    payload = {
        **base,
        "stage": "MEASUREMENT",
        "calibration_lock_path": str(base_path),
        "calibration_lock_sha256": base["_self_sha256"],
        "calibration_result_sha256": sha256(calibration),
        "calibration_result_commit": calibration_commit,
        "calibration_result_path": str(calibration),
        "measurement_runner_sha256": sha256(Path(__file__).resolve()),
        "arm_order": MEASUREMENT_ARMS,
        "measurement_pairs": [["L-M1-off", "L-M1-on"], ["L-M2-off", "L-M2-on"]],
        "_self_sha256": None,
    }
    payload["_self_sha256"] = canonical_sha(payload)
    write_once(args.out, payload)


def command_compare(args: argparse.Namespace) -> None:
    repo = args.repo.resolve()
    lock = validate_lock(repo, args.lock.resolve(), "MEASUREMENT")
    calibration_path = Path(lock["calibration_result_path"])
    calibration_commit = committed(repo, calibration_path, lock["calibration_result_sha256"])
    if calibration_commit != lock.get("calibration_result_commit"):
        raise ValueError("calibration result commit differs from measurement lock")
    calibration = json.loads(calibration_path.read_text())
    if calibration.get("_self_sha256") != canonical_sha(calibration):
        raise ValueError("calibration result self-hash mismatch")
    calibration_base = validate_lock(repo, Path(lock["calibration_lock_path"]), "CALIBRATION")
    if calibration.get("lock_sha256") != lock.get("calibration_lock_sha256") or calibration_base.get(
        "_self_sha256"
    ) != lock.get("calibration_lock_sha256"):
        raise ValueError("measurement lock is not bound to the committed calibration lock")
    root = args.campaign.resolve()
    series: dict[str, dict[str, Any]] = {}
    for name in lock["arm_order"]:
        arm_dir = root / name
        job_log = arm_dir / "job.log"
        try:
            series[name] = validate_arm(arm_dir, lock, name, job_log)
        except FileNotFoundError as exc:
            verdict = {
                "schema": "TASK11_NATIVE_LOSS_VERDICT/v1",
                "status": "INCOMPLETE",
                "reason": str(exc),
                "product_sha": PRODUCT_SHA,
                "measurement_lock_sha256": lock["_self_sha256"],
                "calibration_result_sha256": lock["calibration_result_sha256"],
                "_self_sha256": None,
            }
            verdict["_self_sha256"] = canonical_sha(verdict)
            write_once(args.out, verdict)
            return
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            verdict = {
                "schema": "TASK11_NATIVE_LOSS_VERDICT/v1",
                "status": "INVALID",
                "reason": str(exc),
                "product_sha": PRODUCT_SHA,
                "measurement_lock_sha256": lock["_self_sha256"],
                "calibration_result_sha256": lock["calibration_result_sha256"],
                "_self_sha256": None,
            }
            verdict["_self_sha256"] = canonical_sha(verdict)
            write_once(args.out, verdict)
            return
    pairs = []
    all_pass = True
    for left, right in lock["measurement_pairs"]:
        a, b = series[left], series[right]
        result = compare_pair(a, b, calibration["tolerances"])
        all_pass &= result["pass"]
        pairs.append({"pair": [left, right], **result})
    verdict = {
        "schema": "TASK11_NATIVE_LOSS_VERDICT/v1",
        "status": "PASS_WITHIN_OFF_OFF_ENVELOPE"
        if all_pass
        else ("INVALID" if any(not pair["eligible"] for pair in pairs) else "NOT_PASS"),
        "scope": "Native loss/grad supplement only; not parameter equivalence, accuracy, C1 or overall C2 verdict.",
        "product_sha": PRODUCT_SHA,
        "measurement_lock_sha256": lock["_self_sha256"],
        "calibration_result_sha256": lock["calibration_result_sha256"],
        "pairs": pairs,
        "_self_sha256": None,
    }
    verdict["_self_sha256"] = canonical_sha(verdict)
    write_once(args.out, verdict)


def command_run(args: argparse.Namespace) -> None:
    repo, product = args.repo.resolve(), args.product.resolve()
    lock_path = args.lock.resolve()
    lock = validate_lock(repo, lock_path, args.stage.upper())
    product_preflight(product)
    if sha256(product / RECIPE_REL) != lock["recipe_sha256"]:
        raise ValueError("recipe hash mismatch")
    if sha256(Path(lock["dataset_path"])) != lock["dataset_sha256"]:
        raise ValueError("dataset hash mismatch")
    env_path = args.env_fingerprint.resolve()
    committed(repo, env_path, lock["environment_fingerprint_sha256"])
    actual_gcs = discover_gcs_address()
    address_digest = hashlib.sha256(
        json.dumps([args.dashboard, actual_gcs], separators=(",", ":")).encode()
    ).hexdigest()
    if address_digest != lock["dashboard_gcs_sha256"]:
        raise ValueError("cluster endpoints differ from frozen launch context")
    args.gcs = actual_gcs
    training_paths = [args.venv, args.megatron, args.bridge]
    training_paths_digest = hashlib.sha256(json.dumps(training_paths, separators=(",", ":")).encode()).hexdigest()
    if training_paths_digest != lock["training_paths_sha256"]:
        raise ValueError("training environment paths differ from frozen launch context")
    runtime = lock["runtime"]
    current_runtime = {
        "model_path": MODEL_PATH,
        "model_tree_sha256": tree_sha256(Path(MODEL_PATH)),
        "model_config_relpath": MODEL_CONFIG_PATH,
        "model_config_sha256": sha256(product / MODEL_CONFIG_PATH),
        "training_venv": args.venv,
        "training_venv_python": subprocess.check_output(
            [f"{args.venv}/bin/python", "--version"], text=True, stderr=subprocess.STDOUT
        ).strip(),
        "training_pip_freeze_sha256": pip_freeze_sha256(Path(args.venv)),
        "megatron_python_tree_sha256": tree_sha256(Path(args.megatron), {".py"}),
        "bridge_python_tree_sha256": tree_sha256(Path(args.bridge), {".py"}),
        "num_gpus": 4,
        "save": 0,
    }
    if current_runtime != runtime:
        raise ValueError("actual model/config/training stack differs from frozen environment identity")
    if host_environment_sha256() != lock["host_environment_sha256"]:
        raise ValueError("allowlisted host environment differs from frozen launch context")
    if args.gpu_lock.resolve() != SHARED_GPU_LOCK:
        raise ValueError(f"GPU lock must be the shared launcher lock: {SHARED_GPU_LOCK}")
    if args.stage == "calibration" and lock["arm_order"] != CALIBRATION_ARMS:
        raise ValueError("calibration arm order differs")
    if args.stage == "measurement" and lock["arm_order"] != MEASUREMENT_ARMS:
        raise ValueError("measurement arm order differs")
    if args.out.exists():
        raise ValueError("campaign directory already exists; automatic resume is forbidden")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.gpu_lock.parent.mkdir(parents=True, exist_ok=True)
    with args.gpu_lock.open("a") as gpu_lock:
        fcntl.flock(gpu_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        preflight = subprocess.run(
            [sys.executable, str(product / "scripts/tools/ray_job_preflight.py"), "--address", args.dashboard],
            check=False,
            timeout=60,
        )
        if preflight.returncode:
            raise RuntimeError("cluster failed pre-campaign idle/resource preflight")
        args.out.mkdir()
        for name in lock["arm_order"]:
            run_one(args, repo, product, lock, lock_path, name)


def run_one(
    args: argparse.Namespace, repo: Path, product: Path, lock: dict[str, Any], lock_path: Path, name: str
) -> None:
    from ray.job_submission import JobSubmissionClient

    arm_dir = args.out / name
    arm_dir.mkdir()
    enabled = name.endswith("-on")
    job_id = f"codex-t11-native-{PRODUCT_SHA[:8]}-{args.stage}-{name}"[:100]
    client = JobSubmissionClient(args.dashboard)
    if any(job.submission_id == job_id for job in client.list_jobs()):
        raise ValueError(f"Ray job ID already exists: {job_id}")
    allowed_host_env = ("PATH", "HOME", "LD_LIBRARY_PATH", "LANG", "LC_ALL", "TERM", "CUDA_HOME")
    environment = {key: os.environ[key] for key in allowed_host_env if key in os.environ}
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        environment[key] = ""
    environment["NO_PROXY"] = environment["no_proxy"] = "*"
    if enabled:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        environment.update(ON_PROFILE)
        environment.update(
            {
                "RELAX_STRAGGLER_OUTPUT_DIR": str(arm_dir / "straggler"),
                "RELAX_STRAGGLER_COLLECTOR_ADDR": f"127.0.0.1:{port}",
            }
        )
    environment.update(
        {
            "RELAX": str(product),
            "WORKING_DIR": str(product),
            "RAY_ADDRESS": args.dashboard,
            "TRAIN_RAY_ADDRESS": args.gcs,
            "TRAIN_VENV": args.venv,
            "MEGATRON": args.megatron,
            "PYTHONPATH": args.bridge,
            "PROMPT_SET": lock["dataset_path"],
            "RELAX_RAY_JOB_SAFE_SUBMIT": "1",
            "MODEL_PATH": lock["runtime"]["model_path"],
            "MODEL_CONFIG_DIR": str(product / "scripts/models"),
            "NUM_GPUS": "4",
            "RAY_NO_WAIT": "1",
            "RAY_JOB_SUBMISSION_ID": job_id,
            "RELAX_GPU_LOCK_FILE": str(args.gpu_lock),
            # The parent holds the shared launcher lock for the full Ray job lifetime.
            # This marker makes ray-job.sh reuse that lock instead of deadlocking on it.
            "RELAX_GPU_LOCK_HELD": "task11-native-loss-parent-lock",
            "RELAX_GPU_LOCK_PROJECT": "task11-native-loss-927c5de",
            "SAVE": "0",
            "NUM_ROLLOUT": str(STEPS),
            "GLOBAL_BATCH_SIZE": str(GBS),
            "SAVE_DIR": str(arm_dir / "checkpoint-root"),
            "LOG_DIR": str(arm_dir / "submit-logs"),
            "TENSORBOARD_DIR": str(arm_dir / "tensorboard"),
            "EXP_NAME": name,
        }
    )
    recipe_args = ["--seed", str(SEED)]
    manifest = {
        "schema": "TASK11_NATIVE_LOSS_ARM/v1",
        "arm": name,
        "lock_sha256": lock["_self_sha256"],
        "product_sha": PRODUCT_SHA,
        "recipe_sha256": lock["recipe_sha256"],
        "dataset_sha256": lock["dataset_sha256"],
        "environment_fingerprint_sha256": lock["environment_fingerprint_sha256"],
        "job_id": job_id,
        "save": 0,
        "recipe_args": recipe_args,
        "status": "SUBMITTING",
        "launch_spec": {
            "product_sha": PRODUCT_SHA,
            "recipe_sha256": lock["recipe_sha256"],
            "dataset_sha256": lock["dataset_sha256"],
            "runtime": lock["runtime"],
            "save": 0,
            "num_gpus": 4,
            "seed": SEED,
            "steps": STEPS,
            "gbs": GBS,
            "observer": ON_PROFILE if enabled else {},
            "recipe_args": recipe_args,
        },
        "resources_returned": False,
        "started_at": time.time(),
        "valid": False,
    }
    manifest_path = arm_dir / "manifest.json"
    manifest["_self_sha256"] = canonical_sha(manifest)
    write_once(manifest_path, manifest)
    try:
        launcher = product / "scripts/entrypoint/ray-job.sh"
        dry_run_args = arm_dir / "train-argv.nul"
        environment["DRY_RUN"] = "1"
        environment["TRAIN_ARGS_DUMP"] = str(dry_run_args)
        with (arm_dir / "dry-run.log").open("x") as log:
            dry_run = subprocess.run(
                ["bash", str(launcher), lock["recipe_relpath"], *recipe_args],
                cwd=product,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=180,
            )
        if dry_run.returncode or not dry_run_args.is_file():
            raise RuntimeError("recipe dry-run failed to produce resolved argv")
        argv = validate_resolved_argv(dry_run_args.read_bytes())
        manifest["save_flag_absent"] = True
        manifest["resolved_argv_sha256"] = sha256(dry_run_args)
        manifest["resolved_argv_count"] = len(argv)
        environment.pop("DRY_RUN")
        environment.pop("TRAIN_ARGS_DUMP")
        with (arm_dir / "submit.log").open("x") as log:
            process = subprocess.run(
                ["bash", str(launcher), lock["recipe_relpath"], *recipe_args],
                cwd=product,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=300,
            )
        if process.returncode != 0:
            raise RuntimeError(f"safe Ray submission failed with {process.returncode}")
        deadline, status = time.monotonic() + 1500, "RUNNING"
        while time.monotonic() < deadline:
            status = str(client.get_job_status(job_id))
            (arm_dir / "job.log").write_text(client.get_job_logs(job_id))
            if status in {"SUCCEEDED", "FAILED", "STOPPED"}:
                break
            time.sleep(5)
        if status != "SUCCEEDED":
            raise RuntimeError(f"owned Ray job ended as {status}")
        manifest["status"] = status
        manifest["job_log_sha256"] = sha256(arm_dir / "job.log")
        manifest["native"] = parse_arm(arm_dir, expected_steps=STEPS)
        checkpoint_path = arm_dir / "checkpoint-root" / "sft" / name
        manifest["checkpoint_path"] = str(checkpoint_path)
        manifest["checkpoint_directory_created"] = checkpoint_path.exists()
        roots = sorted(
            set(
                re.findall(
                    r"straggler provenance: relax_root=(\S+)", (arm_dir / "job.log").read_text(errors="replace")
                )
            )
        )
        manifest["worker_source_roots"] = roots
        source_hashes = {root: source_fingerprint(Path(root)) for root in roots}
        manifest["worker_source_sha256"] = source_hashes
        if not roots or any(value != lock["straggler_source_sha256"] for value in source_hashes.values()):
            raise RuntimeError("worker source provenance differs from locked product sources")
        manifest["resources_returned"] = wait_idle(product, args.dashboard)
        manifest["finished_at"] = time.time()
        manifest["valid"] = (
            bool(manifest["native"].get("native_valid"))
            and manifest["resources_returned"]
            and not manifest["checkpoint_directory_created"]
        )
        if not manifest["valid"]:
            raise RuntimeError("native arm failed a data, resource, or SAVE=0 gate")
    except BaseException as exc:
        manifest["error"] = str(exc)
        raise
    finally:
        try:
            status = str(client.get_job_status(job_id))
            if status not in {"SUCCEEDED", "FAILED", "STOPPED"}:
                client.stop_job(job_id)
                manifest["owned_stop_requested"] = True
            if (arm_dir / "job.log").exists():
                manifest["job_log_sha256"] = sha256(arm_dir / "job.log")
        except Exception as exc:
            manifest["final_status_error"] = str(exc)
        manifest["finished_at"] = time.time()
        manifest["_self_sha256"] = canonical_sha(manifest)
        temp = manifest_path.with_suffix(".tmp")
        temp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        temp.replace(manifest_path)
    if not manifest.get("valid"):
        raise RuntimeError(f"{name} invalid; stop campaign without resuming")


def wait_idle(product: Path, dashboard: str) -> bool:
    preflight = product / "scripts/tools/ray_job_preflight.py"
    for _ in range(12):
        result = subprocess.run(
            [sys.executable, str(preflight), "--address", dashboard], capture_output=True, timeout=60
        )
        if result.returncode == 0:
            return True
        time.sleep(5)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-calibration-lock")
    for arg, kind in (("repo", Path), ("product", Path), ("dataset", Path), ("env-fingerprint", Path), ("out", Path)):
        create.add_argument(f"--{arg}", type=kind, required=True)
    create.add_argument("--dashboard", required=True)
    create.add_argument("--gcs", choices=("auto",), required=True)
    create.set_defaults(func=command_create_lock)
    freeze = sub.add_parser("freeze-calibration")
    for arg in ("repo", "lock", "campaign", "out"):
        freeze.add_argument(f"--{arg}", type=Path, required=True)
    freeze.set_defaults(func=command_freeze_calibration)
    measure = sub.add_parser("create-measurement-lock")
    measure.add_argument("--repo", type=Path, required=True)
    measure.add_argument("--calibration-result", type=Path, required=True)
    measure.add_argument("--out", type=Path, required=True)
    measure.set_defaults(func=command_create_measurement_lock)
    run = sub.add_parser("run")
    for arg in ("repo", "product", "lock", "gpu-lock"):
        run.add_argument(f"--{arg}", type=Path, required=True)
    run.add_argument("--campaign", dest="out", type=Path, required=True)
    run.add_argument("--env-fingerprint", type=Path, required=True)
    run.add_argument("--stage", choices=("calibration", "measurement"), required=True)
    for arg in ("dashboard", "gcs", "venv", "megatron", "bridge"):
        run.add_argument(
            f"--{arg}",
            default={"venv": TRAIN_VENV, "megatron": MEGATRON_PATH, "bridge": BRIDGE_PATH}.get(arg),
            required=arg in {"dashboard", "gcs"},
        )
    run.set_defaults(func=command_run)
    compare = sub.add_parser("compare")
    for arg in ("repo", "lock", "campaign", "out"):
        compare.add_argument(f"--{arg}", type=Path, required=True)
    compare.set_defaults(func=command_compare)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
