#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Executable C3 campaign runner for product build 927c5de.

Drives the two arms frozen in ``C3_EVENT_CHAIN_PROTOCOL_927C5DE.md``: a
healthy ON baseline (false-positive check) and a real-slowdown ON arm whose
rank-3 GPU gets a bounded competing CUDA process, started only after the job
reaches RUNNING and killed by explicit PID at terminal state. Arms submit
through the repository launcher (``ray-job.sh`` entrypoint mode), carry
driver/worker provenance, and retain the straggler JSONL plus the TensorBoard
event files the protocol's rollout-level confirmation reads.

The default is non-executing; Ray submission requires ``execute --allow-run``
and a committed lock.
"""

import argparse
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from c2_parameter_campaign_927c5de import (
    _preflight,
    _resources,
    _run_process,
    _source_fingerprint,
    _worker_provenance,
    atomic_new_json,
    canonical_hash,
    require_clean_head,
    sha256_file,
)


ARMS = ["C3-healthy-on", "C3-slow-on"]
ON_PROFILE = {
    "RELAX_STRAGGLER_ENABLE": "1",
    "RELAX_STRAGGLER_WINDOW_S": "5",
    "RELAX_STRAGGLER_WARMUP_WINDOWS": "2",
    "RELAX_STRAGGLER_REPORT_INTERVAL_S": "10",
}
SPINNER_SPEC = {
    "gpu": 3,
    "duty_ms": 30.0,
    "idle_ms": 10.0,
    "start_after": "RUNNING",
    "kill_at": "terminal",
    "kill": "by_pid",
}


def load_lock(path: Path) -> dict[str, Any]:
    lock = json.loads(path.read_text())
    validate_lock(lock)
    return lock


def validate_lock(lock: dict[str, Any]) -> None:
    if lock.get("SCHEMA") != "C3_CAMPAIGN_927C5DE/v1":
        raise ValueError("wrong or missing lock schema")
    if lock.get("_self_sha256") != canonical_hash(lock):
        raise ValueError("lock self hash mismatch")
    for key, length in (
        ("PRODUCT_SHA", 40),
        ("RECIPE_SHA256", 64),
        ("DATASET_SHA256", 64),
        ("ENV_FINGERPRINT_SHA256", 64),
        ("PROTOCOL_SHA256", 64),
        ("RUNNER_SHA256", 64),
        ("SPINNER_SHA256", 64),
    ):
        if not re.fullmatch(rf"[0-9a-f]{{{length}}}", str(lock.get(key, ""))):
            raise ValueError(f"missing or invalid {key}")
    if type(lock.get("EXPECTED_STEPS")) is not int or lock["EXPECTED_STEPS"] <= 0:
        raise ValueError("EXPECTED_STEPS must be positive")
    if lock.get("SAVE") != "0":
        raise ValueError("C3 arms run SAVE=0")
    if lock.get("ARM_ORDER") != ARMS:
        raise ValueError("arm order differs from the frozen protocol")
    if lock.get("SPINNER_SPEC") != SPINNER_SPEC:
        raise ValueError("spinner specification differs from the frozen protocol")
    if lock.get("TOPOLOGY") != {"kind": "DP4", "gpus": 4}:
        raise ValueError("only the DP4 four-GPU topology is valid")


def lock_payload(args: argparse.Namespace) -> dict[str, Any]:
    product = Path(args.product).resolve()
    for path in map(Path, (args.recipe, args.dataset, args.environment, args.protocol, args.spinner)):
        if not path.is_file():
            raise ValueError(f"missing frozen input: {path}")
    return {
        "SCHEMA": "C3_CAMPAIGN_927C5DE/v1",
        "PRODUCT_SHA": require_clean_head(product),
        "RECIPE_PATH": str(Path(args.recipe).resolve()),
        "RECIPE_SHA256": sha256_file(Path(args.recipe)),
        "DATASET_PATH": str(Path(args.dataset).resolve()),
        "DATASET_SHA256": sha256_file(Path(args.dataset)),
        "ENV_FINGERPRINT_PATH": str(Path(args.environment).resolve()),
        "ENV_FINGERPRINT_SHA256": sha256_file(Path(args.environment)),
        "PROTOCOL_PATH": str(Path(args.protocol).resolve()),
        "PROTOCOL_SHA256": sha256_file(Path(args.protocol)),
        "SPINNER_PATH": str(Path(args.spinner).resolve()),
        "SPINNER_SHA256": sha256_file(Path(args.spinner)),
        "RUNNER_PATH": str(Path(__file__).resolve()),
        "RUNNER_SHA256": sha256_file(Path(__file__)),
        "EXPECTED_STEPS": int(args.expected_steps),
        "SAVE": "0",
        "ARM_ORDER": ARMS,
        "ON_PROFILE": ON_PROFILE,
        "SPINNER_SPEC": SPINNER_SPEC,
        "TOPOLOGY": {"kind": "DP4", "gpus": 4},
        "RECIPE_ENV": {"SAVE": "0", "NUM_ROLLOUT": str(args.expected_steps), "GLOBAL_BATCH_SIZE": "32"},
    }


def _straggler_artifacts(arm_dir: Path) -> dict[str, Any]:
    """The protocol's retained observable outputs, counted as-is.

    The runtime nests every artifact under ``run_<id>/`` inside the configured
    output directory (found on the real healthy arm 2026-09-29), so the files
    are located recursively — a direct-path check wrongly failed the arm.
    """
    found: dict[str, Any] = {}
    for name in ("straggler_envelopes.jsonl", "straggler_verdicts.jsonl"):
        path = arm_dir / "straggler"
        hits = sorted(path.rglob(name)) if path.is_dir() else []
        found[name] = hits[0].stat().st_size if hits else None
    found["collector_status_files"] = (
        len(sorted((arm_dir / "straggler").rglob("collector_status*.json"))) if (arm_dir / "straggler").is_dir() else 0
    )
    events = (
        sorted((arm_dir / "tensorboard").rglob("events.out.tfevents.*")) if (arm_dir / "tensorboard").is_dir() else []
    )
    found["tensorboard_event_files"] = len(events)
    return found


def _start_spinner(lock: dict[str, Any], arm_dir: Path) -> subprocess.Popen:
    spec = lock["SPINNER_SPEC"]
    log = (arm_dir / "spinner.log").open("w")
    process = subprocess.Popen(
        [
            sys.executable,
            str(lock["SPINNER_PATH"]),
            str(spec["gpu"]),
            str(spec["duty_ms"]),
            str(spec["idle_ms"]),
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return process


def _kill_spinner(process: subprocess.Popen, manifest: dict[str, Any]) -> None:
    if process.poll() is not None:
        manifest["spinner_exit_before_kill"] = process.returncode
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(process.pid, sig)
            process.wait(timeout=10)
            manifest["spinner_killed_by"] = "SIGTERM" if sig == signal.SIGTERM else "SIGKILL"
            return
        except (ProcessLookupError, subprocess.TimeoutExpired):
            continue
    manifest["spinner_kill_failed"] = True


def _execute_arm(args: argparse.Namespace, lock: dict[str, Any], name: str, lock_sha: str) -> None:
    from ray.job_submission import JobSubmissionClient

    arm_dir = args.out / name
    if arm_dir.exists():
        raise ValueError(f"refusing to overwrite existing arm: {arm_dir}")
    arm_dir.mkdir(parents=True)
    product = args.product.resolve()
    _preflight(product, args.dashboard)
    before = _resources()
    source_before = _source_fingerprint(product)
    job_id = f"codex-c3-{lock['PRODUCT_SHA'][:8]}-{args.out.name}-{name}"[:100]
    client = JobSubmissionClient(args.dashboard)
    if any(job.submission_id == job_id for job in client.list_jobs()):
        raise ValueError(f"owned submission ID already exists: {job_id}")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("RELAX_STRAGGLER_", "RELAX_KERNEL_CACHE_")):
            del env[key]
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env[key] = ""
    env["NO_PROXY"] = env["no_proxy"] = "*"
    env.update(
        {
            **ON_PROFILE,
            "RELAX_STRAGGLER_OUTPUT_DIR": str(arm_dir / "straggler"),
            "RELAX_STRAGGLER_COLLECTOR_ADDR": f"127.0.0.1:{port}",
            "RELAX": str(product),
            "WORKING_DIR": str(product),
            "RAY_ADDRESS": args.dashboard,
            "TRAIN_RAY_ADDRESS": args.gcs,
            "TRAIN_VENV": args.venv,
            "MEGATRON": args.megatron,
            "PYTHONPATH": args.bridge,
            "PROMPT_SET": str(lock["DATASET_PATH"]),
            "RELAX_RAY_JOB_SAFE_SUBMIT": "1",
            "RAY_NO_WAIT": "1",
            "RAY_JOB_SUBMISSION_ID": job_id,
            "SAVE": "0",
            "NUM_ROLLOUT": str(lock["EXPECTED_STEPS"]),
            "GLOBAL_BATCH_SIZE": lock["RECIPE_ENV"]["GLOBAL_BATCH_SIZE"],
            "SAVE_DIR": str(arm_dir / "checkpoints"),
            "LOG_DIR": str(arm_dir / "submit-logs"),
            "TENSORBOARD_DIR": str(arm_dir / "tensorboard"),
            "EXP_NAME": name,
        }
    )
    manifest = {
        "run_id": name,
        "stage": "C3",
        "job_id": job_id,
        "lock_sha256": lock_sha,
        "git": {"commit": lock["PRODUCT_SHA"], "dirty": False},
        "product_sha": lock["PRODUCT_SHA"],
        "recipe_sha256": lock["RECIPE_SHA256"],
        "dataset_sha256": lock["DATASET_SHA256"],
        "env_fingerprint_sha256": lock["ENV_FINGERPRINT_SHA256"],
        "protocol_sha256": lock["PROTOCOL_SHA256"],
        "runner_sha256": lock["RUNNER_SHA256"],
        "spinner_sha256": lock["SPINNER_SHA256"],
        "spinner_spec": lock["SPINNER_SPEC"] if name == "C3-slow-on" else None,
        "expected_steps": lock["EXPECTED_STEPS"],
        "save": 0,
        "resources_before": before,
        "driver_source_sha256_before": source_before,
        "worker_source_hashes": {},
        "valid": False,
        "started_at": time.time(),
    }
    path = arm_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    spinner: subprocess.Popen | None = None
    try:
        launcher = product / "scripts" / "entrypoint" / "ray-job.sh"
        if not launcher.is_file():
            raise RuntimeError(f"missing repository launcher: {launcher}")
        _run_process(["bash", str(launcher), str(lock["RECIPE_PATH"])], product, env, arm_dir / "submit.log")
        deadline = time.monotonic() + 1500
        status = "PENDING"
        spinner_started = False
        while time.monotonic() < deadline:
            status = str(client.get_job_status(job_id))
            (arm_dir / "job.log").write_text(client.get_job_logs(job_id))
            if name == "C3-slow-on" and not spinner_started and status == "RUNNING":
                spinner = _start_spinner(lock, arm_dir)
                manifest["spinner_pid"] = spinner.pid
                manifest["spinner_started_at_status"] = status
                spinner_started = True
            if status in {"SUCCEEDED", "FAILED", "STOPPED"}:
                break
            time.sleep(5)
        if status != "SUCCEEDED":
            raise RuntimeError(f"owned job status: {status}")
        manifest["job_status"] = status
        manifest["worker_source_hashes"] = _worker_provenance(arm_dir / "job.log")
        manifest["driver_source_sha256_after"] = _source_fingerprint(product)
        try:
            _preflight(product, args.dashboard)
            manifest["resources_returned"] = True
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            manifest["resource_release_error"] = str(exc)
            manifest["resources_returned"] = False
        manifest["resources_after"] = _resources()
        manifest["straggler_artifacts"] = _straggler_artifacts(arm_dir)
        manifest["valid"] = (
            manifest["driver_source_sha256_before"] == manifest["driver_source_sha256_after"]
            and bool(manifest["worker_source_hashes"])
            and all(value == source_before for value in manifest["worker_source_hashes"].values())
            and manifest["straggler_artifacts"]["straggler_verdicts.jsonl"] is not None
            and manifest["straggler_artifacts"]["tensorboard_event_files"] > 0
        )
        if not manifest["valid"]:
            raise RuntimeError("arm provenance/artifact gate failed")
    except Exception as exc:
        manifest["error"] = str(exc)
        raise
    finally:
        if spinner is not None:
            _kill_spinner(spinner, manifest)
        try:
            status = str(client.get_job_status(job_id))
            if status not in {"SUCCEEDED", "FAILED", "STOPPED"}:
                client.stop_job(job_id)
                manifest["owned_job_stop_requested"] = True
            (arm_dir / "job.log").write_text(client.get_job_logs(job_id))
        except Exception as exc:
            manifest["final_status_error"] = str(exc)
        manifest["finished_at"] = time.time()
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def cmd_lock(args: argparse.Namespace) -> int:
    payload = lock_payload(args)
    validate_lock({**payload, "_self_sha256": canonical_hash(payload)})
    atomic_new_json(args.out / "C3_LOCK.json", payload)
    return 0


def cmd_execute(args: argparse.Namespace) -> int:
    if not args.allow_run:
        raise ValueError("refusing GPU/Ray submission without --allow-run")
    lock_path = args.lock.resolve()
    lock = load_lock(lock_path)
    names = [item.strip() for item in args.arms.split(",") if item.strip()]
    if names != lock["ARM_ORDER"]:
        raise ValueError("requested arms must equal the frozen order; no partial runs")
    product = args.product.resolve()
    if require_clean_head(product) != lock["PRODUCT_SHA"]:
        raise ValueError("product SHA drift")
    for path_key, hash_key in (
        ("RECIPE_PATH", "RECIPE_SHA256"),
        ("DATASET_PATH", "DATASET_SHA256"),
        ("ENV_FINGERPRINT_PATH", "ENV_FINGERPRINT_SHA256"),
        ("PROTOCOL_PATH", "PROTOCOL_SHA256"),
        ("SPINNER_PATH", "SPINNER_SHA256"),
        ("RUNNER_PATH", "RUNNER_SHA256"),
    ):
        if sha256_file(Path(lock[path_key])) != lock[hash_key]:
            raise ValueError(f"frozen input drift: {path_key}")
    if args.out.exists():
        raise ValueError("campaign output already exists; no overwrite/resume")
    args.out.mkdir(parents=True)
    lock_sha = sha256_file(lock_path)
    for name in names:
        _execute_arm(args, lock, name, lock_sha)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    lock_parser = sub.add_parser("lock")
    lock_parser.add_argument("--product", type=Path, required=True)
    lock_parser.add_argument("--recipe", type=Path, required=True)
    lock_parser.add_argument("--dataset", type=Path, required=True)
    lock_parser.add_argument("--environment", type=Path, required=True)
    lock_parser.add_argument("--protocol", type=Path, required=True)
    lock_parser.add_argument("--spinner", type=Path, required=True)
    lock_parser.add_argument("--expected-steps", type=int, default=48)
    lock_parser.add_argument("--out", type=Path, required=True)
    lock_parser.set_defaults(func=cmd_lock)
    execute = sub.add_parser("execute")
    execute.add_argument("--allow-run", action="store_true")
    execute.add_argument("--lock", type=Path, required=True)
    execute.add_argument("--arms", required=True)
    execute.add_argument("--out", type=Path, required=True)
    execute.add_argument("--product", type=Path, required=True)
    execute.add_argument("--dashboard", required=True)
    execute.add_argument("--gcs", required=True)
    execute.add_argument("--venv", required=True)
    execute.add_argument("--megatron", required=True)
    execute.add_argument("--bridge", required=True)
    execute.set_defaults(func=cmd_execute)
    args = parser.parse_args()
    try:
        return args.func(args)
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
