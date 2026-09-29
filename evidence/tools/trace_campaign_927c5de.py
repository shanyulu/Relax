#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Executable, two-stage C2 overlap campaign runner for product build 927c5de.

Submission twin of ``trace_verdict_927c5de.py``: it locks the exact four-OFF
calibration and AB/BA measurement arm orders, drives each arm through the
frozen recipe with ``--overlap-grad-reduce`` and the torch profiler enabled,
and proves driver/worker provenance, job completion, unique DP4 rank trace
coverage, and returned resources for every arm.  Freezing the OFF/OFF
envelope and verdicting the ON/OFF pairs stay in ``trace_verdict_927c5de.py``.

The default is non-executing.  Ray submission requires ``execute --allow-run``
and a committed stage lock; this is an intentional guard against accidental
GPU use while preparing evidence.
"""

import argparse
import hashlib
import json
import re
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
    git,
    require_clean_head,
    sha256_file,
)
from trace_overlap_metrics import aggregate


CALIBRATION_ARMS = ["O-C1-off", "O-C2-off", "O-C3-off", "O-C4-off"]
MEASUREMENT_ARMS = ["O-M1-off", "O-M1-on", "O-M2-on", "O-M2-off"]
#: Profiler window and topology flags appended to every arm's recipe call.
#: The per-arm ``--tb-experiment-name`` (absolute, on the data disk) is added
#: by the executor so each arm's traces land under its own directory.
TRACE_ARGS = [
    "--use-pytorch-profiler",
    "--profile-step-start",
    "9",
    "--profile-step-end",
    "24",
    "--overlap-grad-reduce",
]
ON_PROFILE = {
    "RELAX_STRAGGLER_ENABLE": "1",
    "RELAX_STRAGGLER_WINDOW_S": "5",
    "RELAX_STRAGGLER_WARMUP_WINDOWS": "2",
    "RELAX_STRAGGLER_REPORT_INTERVAL_S": "10",
}


def load_lock(path: Path) -> dict[str, Any]:
    lock = json.loads(path.read_text())
    validate_lock(lock)
    return lock


def validate_lock(lock: dict[str, Any]) -> None:
    if lock.get("SCHEMA") != "TRACE_OVERLAP_CAMPAIGN_927C5DE/v1":
        raise ValueError("wrong or missing lock schema")
    if lock.get("_self_sha256") != canonical_hash(lock):
        raise ValueError("lock self hash mismatch")
    stage = lock.get("STAGE")
    if stage not in {"CALIBRATION", "MEASUREMENT"}:
        raise ValueError("invalid lock stage")
    for key, length in (
        ("PRODUCT_SHA", 40),
        ("RECIPE_SHA256", 64),
        ("DATASET_SHA256", 64),
        ("ENV_FINGERPRINT_SHA256", 64),
        ("PROTOCOL_SHA256", 64),
        ("ANALYZER_SHA256", 64),
        ("RUNNER_SHA256", 64),
    ):
        if not re.fullmatch(rf"[0-9a-f]{{{length}}}", str(lock.get(key, ""))):
            raise ValueError(f"missing or invalid {key}")
    if type(lock.get("EXPECTED_STEPS")) is not int or lock["EXPECTED_STEPS"] <= 0:
        raise ValueError("EXPECTED_STEPS must be positive")
    if lock.get("SAVE") != "0" or lock.get("CHECKPOINT_POLICY") != "NONE_TRACES_ONLY":
        raise ValueError("overlap arms must run SAVE=0 with traces as the only retained artifact")
    if lock.get("TRACE_ARGS") != TRACE_ARGS:
        raise ValueError("trace arguments differ from the frozen protocol")
    if lock.get("TOPOLOGY") != {"kind": "DP4", "gpus": 4}:
        raise ValueError("only the DP4 four-GPU topology is valid")
    expected = CALIBRATION_ARMS if stage == "CALIBRATION" else MEASUREMENT_ARMS
    if lock.get("ARM_ORDER") != expected:
        raise ValueError(f"{stage} arm order differs from frozen protocol")
    if stage == "CALIBRATION":
        if any(not name.endswith("-off") for name in lock["ARM_ORDER"]):
            raise ValueError("calibration must contain OFF arms only")
        if "CALIBRATION_RESULT_SHA256" in lock:
            raise ValueError("calibration lock must not reference a result")
    else:
        if not re.fullmatch(r"[0-9a-f]{64}", str(lock.get("CALIBRATION_RESULT_SHA256", ""))):
            raise ValueError("measurement lock lacks frozen calibration result")
        if not re.fullmatch(r"[0-9a-f]{40}", str(lock.get("CALIBRATION_RESULT_COMMIT", ""))):
            raise ValueError("measurement lock lacks calibration commit")


def lock_payload(args: argparse.Namespace, stage: str) -> dict[str, Any]:
    product = Path(args.product).resolve()
    recipe = Path(args.recipe).resolve()
    dataset = Path(args.dataset).resolve()
    environment = Path(args.environment).resolve()
    protocol = Path(args.protocol).resolve()
    analyzer = Path(args.analyzer).resolve()
    runner = Path(__file__).resolve()
    for path in (recipe, dataset, environment, protocol, analyzer, runner):
        if not path.is_file():
            raise ValueError(f"missing frozen input: {path}")
    payload: dict[str, Any] = {
        "SCHEMA": "TRACE_OVERLAP_CAMPAIGN_927C5DE/v1",
        "STAGE": stage,
        "PRODUCT_SHA": require_clean_head(product),
        "RECIPE_PATH": str(recipe),
        "RECIPE_SHA256": sha256_file(recipe),
        "DATASET_PATH": str(dataset),
        "DATASET_SHA256": sha256_file(dataset),
        "ENV_FINGERPRINT_PATH": str(environment),
        "ENV_FINGERPRINT_SHA256": sha256_file(environment),
        "PROTOCOL_PATH": str(protocol),
        "PROTOCOL_SHA256": sha256_file(protocol),
        "ANALYZER_PATH": str(analyzer),
        "ANALYZER_SHA256": sha256_file(analyzer),
        "RUNNER_PATH": str(runner),
        "RUNNER_SHA256": sha256_file(runner),
        "EXPECTED_STEPS": int(args.expected_steps),
        "SAVE": "0",
        "CHECKPOINT_POLICY": "NONE_TRACES_ONLY",
        "TRACE_ARGS": TRACE_ARGS,
        "TRACE_DIR_TEMPLATE": "{out}/{arm}/train_trace",
        "TOPOLOGY": {"kind": "DP4", "gpus": 4},
        "ARM_ORDER": CALIBRATION_ARMS if stage == "CALIBRATION" else MEASUREMENT_ARMS,
        "RECIPE_ENV": {"SAVE": "0", "NUM_ROLLOUT": str(args.expected_steps), "GLOBAL_BATCH_SIZE": "32"},
        "ON_PROFILE": ON_PROFILE,
    }
    if stage == "MEASUREMENT":
        payload.update(
            {
                "CALIBRATION_RESULT_SHA256": sha256_file(Path(args.calibration_result)),
                "CALIBRATION_RESULT_COMMIT": committed_calibration(args.calibration_result, args.evidence_repo),
            }
        )
    return payload


def committed_calibration(result_path: Path, evidence_repo: Path) -> str:
    """Require an exact committed freeze result; uncommitted JSON cannot
    unlock measurement."""
    result_path = result_path.resolve()
    evidence_repo = evidence_repo.resolve()
    relative = result_path.relative_to(evidence_repo)
    if git(evidence_repo, "status", "--porcelain", "--", str(relative)):
        raise ValueError("calibration result has uncommitted changes")
    commit = git(evidence_repo, "log", "-1", "--format=%H", "--", str(relative))
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("calibration result is not committed")
    committed = subprocess.check_output(["git", "-C", str(evidence_repo), "show", f"{commit}:{relative}"], text=False)
    if hashlib.sha256(committed).hexdigest() != sha256_file(result_path):
        raise ValueError("working calibration result differs from committed blob")
    result = json.loads(result_path.read_text())
    if result.get("kind") != "calibration_result" or result.get("verdict") != "PASS":
        raise ValueError("calibration result is not a passing freeze")
    return commit


def _validate_execution(args: argparse.Namespace, lock: dict[str, Any], names: list[str]) -> None:
    validate_lock(lock)
    if names != lock["ARM_ORDER"]:
        raise ValueError("requested arms must equal the frozen stage order; no implicit resume")
    product = args.product.resolve()
    if require_clean_head(product) != lock["PRODUCT_SHA"]:
        raise ValueError("product SHA drift")
    for path_key, hash_key in (
        ("RECIPE_PATH", "RECIPE_SHA256"),
        ("DATASET_PATH", "DATASET_SHA256"),
        ("ENV_FINGERPRINT_PATH", "ENV_FINGERPRINT_SHA256"),
        ("PROTOCOL_PATH", "PROTOCOL_SHA256"),
        ("ANALYZER_PATH", "ANALYZER_SHA256"),
        ("RUNNER_PATH", "RUNNER_SHA256"),
    ):
        if sha256_file(Path(lock[path_key])) != lock[hash_key]:
            raise ValueError(f"frozen input drift: {path_key}")
    if int(lock["RECIPE_ENV"]["NUM_ROLLOUT"]) != lock["EXPECTED_STEPS"]:
        raise ValueError("locked step count differs from recipe environment")


def _trace_summary(arm_dir: Path) -> dict[str, Any]:
    """Aggregate the arm's raw traces; the analyzer's own rank rules apply."""
    traces = sorted(arm_dir.rglob("*.pt.trace.json.gz"))
    if len(traces) < 4:
        raise ValueError(f"arm retained {len(traces)} trace files; protocol requires four ranks")
    result = aggregate(traces)
    if result["rank_ids"] != [0, 1, 2, 3] or result["ranks_profiled"] != 4:
        raise ValueError("duplicate, missing, or invalid DP4 rank coverage")
    return result


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
    job_id = f"codex-c2o-{lock['PRODUCT_SHA'][:8]}-{args.out.name}-{name}"[:100]
    client = JobSubmissionClient(args.dashboard)
    if any(job.submission_id == job_id for job in client.list_jobs()):
        raise ValueError(f"owned submission ID already exists: {job_id}")
    env = dict(__import__("os").environ)
    for key in list(env):
        if key.startswith(("RELAX_STRAGGLER_", "RELAX_KERNEL_CACHE_")):
            del env[key]
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env[key] = ""
    env["NO_PROXY"] = env["no_proxy"] = "*"
    if name.endswith("-on"):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        env.update(
            {
                **ON_PROFILE,
                "RELAX_STRAGGLER_OUTPUT_DIR": str(arm_dir / "straggler"),
                "RELAX_STRAGGLER_COLLECTOR_ADDR": f"127.0.0.1:{port}",
            }
        )
    env.update(
        {
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
        "stage": lock["STAGE"],
        "job_id": job_id,
        "lock_sha256": lock_sha,
        "git": {"commit": lock["PRODUCT_SHA"], "dirty": False},
        "product_sha": lock["PRODUCT_SHA"],
        "recipe_sha256": lock["RECIPE_SHA256"],
        "dataset_sha256": lock["DATASET_SHA256"],
        "env_fingerprint_sha256": lock["ENV_FINGERPRINT_SHA256"],
        "protocol_sha256": lock["PROTOCOL_SHA256"],
        "analyzer_sha256": lock["ANALYZER_SHA256"],
        "runner_sha256": lock["RUNNER_SHA256"],
        "trace_args": TRACE_ARGS,
        "tb_experiment_name": str(arm_dir),
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
    try:
        # Invoke through the repository launcher (entrypoint mode): it owns the
        # GPU flock, runs the read-only preflight under RELAX_RAY_JOB_SAFE_SUBMIT,
        # sets up MASTER_ADDR / RUNTIME_ENV_JSON, and execs the recipe with
        # RELAX_ENTRYPOINT_MODE already exported — so the recipe skips its
        # local.sh fallback. Invoking the recipe directly made local.sh take the
        # full-local path ("ray status" rejects a dashboard RAY_ADDRESS), whose
        # "pkill -9 python" cleanup killed this runner mid-arm (2026-09-29,
        # O-C1-off first attempt, archived as INVALID).
        launcher = product / "scripts" / "entrypoint" / "ray-job.sh"
        if not launcher.is_file():
            raise RuntimeError(f"missing repository launcher: {launcher}")
        command = ["bash", str(launcher), str(lock["RECIPE_PATH"]), *TRACE_ARGS, "--tb-experiment-name", str(arm_dir)]
        _run_process(command, product, env, arm_dir / "submit.log")
        deadline = time.monotonic() + 1500
        status = "RUNNING"
        while time.monotonic() < deadline:
            status = str(client.get_job_status(job_id))
            (arm_dir / "job.log").write_text(client.get_job_logs(job_id))
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
        trace_summary = _trace_summary(arm_dir)
        manifest["trace_summary"] = {
            "trace_files": len(sorted(arm_dir.rglob("*.pt.trace.json.gz"))),
            "rank_ids": trace_summary["rank_ids"],
            "overlap_ratio_total": trace_summary["overlap_ratio_total"],
            "global_sync_count_total": trace_summary["global_sync_count_total"],
        }
        (arm_dir / "overlap_metrics.json").write_text(json.dumps(trace_summary, indent=2, sort_keys=True) + "\n")
        manifest["valid"] = (
            manifest["driver_source_sha256_before"] == manifest["driver_source_sha256_after"]
            and bool(manifest["worker_source_hashes"])
            and all(value == source_before for value in manifest["worker_source_hashes"].values())
            and manifest["trace_summary"]["rank_ids"] == [0, 1, 2, 3]
        )
        if not manifest["valid"]:
            raise RuntimeError("arm provenance/trace gate failed")
    except Exception as exc:
        manifest["error"] = str(exc)
        raise
    finally:
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


def validate_arm(arm_dir: Path, lock: dict[str, Any], lock_sha: str) -> dict[str, Any]:
    path = arm_dir / "manifest.json"
    if not path.is_file():
        raise ValueError(f"missing manifest: {arm_dir}")
    manifest = json.loads(path.read_text())
    problems = []
    for field, expected in (
        ("lock_sha256", lock_sha),
        ("product_sha", lock["PRODUCT_SHA"]),
        ("recipe_sha256", lock["RECIPE_SHA256"]),
        ("dataset_sha256", lock["DATASET_SHA256"]),
        ("env_fingerprint_sha256", lock["ENV_FINGERPRINT_SHA256"]),
        ("protocol_sha256", lock["PROTOCOL_SHA256"]),
        ("analyzer_sha256", lock["ANALYZER_SHA256"]),
        ("runner_sha256", lock["RUNNER_SHA256"]),
        ("expected_steps", lock["EXPECTED_STEPS"]),
    ):
        if manifest.get(field) != expected:
            problems.append(f"{field} drift")
    if manifest.get("run_id") not in lock["ARM_ORDER"]:
        problems.append("arm not in lock")
    if (
        manifest.get("job_status") != "SUCCEEDED"
        or not manifest.get("valid")
        or not manifest.get("resources_returned")
    ):
        problems.append("unsuccessful or unclean arm")
    if manifest.get("driver_source_sha256_before") != manifest.get("driver_source_sha256_after"):
        problems.append("driver provenance drift")
    workers = manifest.get("worker_source_hashes")
    if (
        not isinstance(workers, dict)
        or not workers
        or any(value != manifest.get("driver_source_sha256_before") for value in workers.values())
    ):
        problems.append("worker provenance missing/drift")
    summary = manifest.get("trace_summary")
    if not isinstance(summary, dict) or summary.get("rank_ids") != [0, 1, 2, 3]:
        problems.append("trace rank coverage missing/invalid")
    traces = sorted(arm_dir.rglob("*.pt.trace.json.gz"))
    if len(traces) != 4:
        problems.append(f"expected exactly four rank traces, found {len(traces)}")
    if problems:
        raise ValueError(f"{arm_dir.name}: {', '.join(problems)}")
    return manifest


def cmd_calibration_lock(args: argparse.Namespace) -> int:
    payload = lock_payload(args, "CALIBRATION")
    validate_lock({**payload, "_self_sha256": canonical_hash(payload)})
    atomic_new_json(args.out / "O_CALIBRATION_LOCK.json", payload)
    return 0


def cmd_measurement_lock(args: argparse.Namespace) -> int:
    payload = lock_payload(args, "MEASUREMENT")
    validate_lock({**payload, "_self_sha256": canonical_hash(payload)})
    atomic_new_json(args.out / "O_MEASUREMENT_LOCK.json", payload)
    return 0


def cmd_execute(args: argparse.Namespace) -> int:
    if not args.allow_run:
        raise ValueError("refusing GPU/Ray submission without --allow-run")
    lock_path = args.lock.resolve()
    lock = load_lock(lock_path)
    names = [item.strip() for item in args.arms.split(",") if item.strip()]
    _validate_execution(args, lock, names)
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
    lock_parser = argparse.ArgumentParser(add_help=False)
    lock_parser.add_argument("--product", type=Path, required=True)
    lock_parser.add_argument("--recipe", type=Path, required=True)
    lock_parser.add_argument("--dataset", type=Path, required=True)
    lock_parser.add_argument("--environment", type=Path, required=True)
    lock_parser.add_argument("--protocol", type=Path, required=True)
    lock_parser.add_argument("--analyzer", type=Path, required=True)
    lock_parser.add_argument("--expected-steps", type=int, default=48)
    lock_parser.add_argument("--out", type=Path, required=True)
    calibration_lock = sub.add_parser("calibration-lock", parents=[lock_parser])
    calibration_lock.set_defaults(func=cmd_calibration_lock)
    measurement_lock = sub.add_parser("measurement-lock", parents=[lock_parser])
    measurement_lock.add_argument("--calibration-result", type=Path, required=True)
    measurement_lock.add_argument("--evidence-repo", type=Path, required=True)
    measurement_lock.set_defaults(func=cmd_measurement_lock)
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
