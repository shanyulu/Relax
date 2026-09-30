#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Executable, two-stage C2 parameter campaign for product build 927c5de.

This successor deliberately does not reuse the historical C2 namespace.  It
locks exactly four OFF calibration arms before the first ON arm can be
submitted, retains checkpoints, and binds the driver, comparator, protocol,
recipe, dataset, environment fingerprint, product and resources to every arm.

The default is non-executing.  Ray submission requires ``execute --allow-run``
and a committed stage lock; this is an intentional guard against accidental
GPU use while preparing evidence.
"""

import argparse
import hashlib
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


CALIBRATION_ARMS = ["P-C1-off", "P-C2-off", "P-C3-off", "P-C4-off"]
MEASUREMENT_ARMS = ["P-M1-off", "P-M1-on", "P-M2-on", "P-M2-off"]
ON_PROFILE = {
    "RELAX_STRAGGLER_ENABLE": "1",
    "RELAX_STRAGGLER_WINDOW_S": "5",
    "RELAX_STRAGGLER_WARMUP_WINDOWS": "2",
    "RELAX_STRAGGLER_REPORT_INTERVAL_S": "10",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(payload: dict[str, Any]) -> str:
    unsigned = {**payload, "_self_sha256": None}
    return hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def require_clean_head(product: Path) -> str:
    head = git(product, "rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("product HEAD is not a full SHA")
    if git(product, "status", "--porcelain"):
        raise ValueError("product worktree is dirty")
    return head


def atomic_new_json(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise ValueError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["_self_sha256"] = canonical_hash(payload)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def load_lock(path: Path) -> dict[str, Any]:
    lock = json.loads(path.read_text())
    validate_lock(lock)
    return lock


def validate_lock(lock: dict[str, Any]) -> None:
    if lock.get("SCHEMA") != "C2_PARAMETER_CAMPAIGN_927C5DE/v1":
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
        ("RUNNER_SHA256", 64),
        ("COMPARATOR_SHA256", 64),
    ):
        if not re.fullmatch(rf"[0-9a-f]{{{length}}}", str(lock.get(key, ""))):
            raise ValueError(f"missing or invalid {key}")
    if type(lock.get("EXPECTED_STEPS")) is not int or lock["EXPECTED_STEPS"] <= 0:
        raise ValueError("EXPECTED_STEPS must be positive")
    if lock.get("SAVE") != 1 or lock.get("CHECKPOINT_POLICY") != "RETAIN_UNTIL_ARCHIVED":
        raise ValueError("checkpoint retention is not locked")
    expected = CALIBRATION_ARMS if stage == "CALIBRATION" else MEASUREMENT_ARMS
    if lock.get("ARM_ORDER") != expected:
        raise ValueError(f"{stage} arm order differs from frozen protocol")
    if lock.get("TOPOLOGY") != {"kind": "DP4", "gpus": 4}:
        raise ValueError("only the DP4 four-GPU topology is valid")
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


def lock_payload(args: argparse.Namespace, stage: str, *, calibration: dict[str, Any] | None = None) -> dict[str, Any]:
    product = Path(args.product).resolve()
    recipe = Path(args.recipe).resolve()
    dataset = Path(args.dataset).resolve()
    environment = Path(args.environment).resolve()
    protocol = Path(args.protocol).resolve()
    runner = Path(__file__).resolve()
    comparator = Path(args.comparator).resolve()
    for path in (recipe, dataset, environment, protocol, runner, comparator):
        if not path.is_file():
            raise ValueError(f"missing frozen input: {path}")
    payload: dict[str, Any] = {
        "SCHEMA": "C2_PARAMETER_CAMPAIGN_927C5DE/v1",
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
        "RUNNER_PATH": str(runner),
        "RUNNER_SHA256": sha256_file(runner),
        "COMPARATOR_PATH": str(comparator),
        "COMPARATOR_SHA256": sha256_file(comparator),
        "EXPECTED_STEPS": int(args.expected_steps),
        "SAVE": 1,
        "CHECKPOINT_POLICY": "RETAIN_UNTIL_ARCHIVED",
        "TOPOLOGY": {"kind": "DP4", "gpus": 4},
        "ARM_ORDER": CALIBRATION_ARMS if stage == "CALIBRATION" else MEASUREMENT_ARMS,
        "RECIPE_ENV": {"SAVE": "1", "NUM_ROLLOUT": str(args.expected_steps), "GLOBAL_BATCH_SIZE": "32"},
        "ON_PROFILE": ON_PROFILE,
    }
    if calibration is not None:
        payload.update(
            {
                "CALIBRATION_RESULT_SHA256": sha256_file(Path(args.calibration_result)),
                "CALIBRATION_RESULT_COMMIT": calibration["_committed_at"],
                "TOLERANCE_TABLE_SHA256": calibration["tolerance_table_sha256"],
            }
        )
    return payload


def committed_calibration(result_path: Path, evidence_repo: Path) -> dict[str, Any]:
    """Require an exact committed result; an uncommitted JSON cannot unlock
    ON."""
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
    from c2_parameter_verdict_927c5de import canonical_sha256

    if result.get("status") != "FROZEN_OFF_ONLY" or result.get("self_sha256") != canonical_sha256(result):
        raise ValueError("calibration result is not a self-hashed frozen result")
    result["_committed_at"] = commit
    return result


def _lock_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--product", type=Path, required=True)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--comparator", type=Path, required=True)
    parser.add_argument("--expected-steps", type=int, default=48)
    parser.add_argument("--out", type=Path, required=True)


def cmd_calibration_lock(args: argparse.Namespace) -> int:
    payload = lock_payload(args, "CALIBRATION")
    validate_lock({**payload, "_self_sha256": canonical_hash(payload)})
    atomic_new_json(args.out / "P_CALIBRATION_LOCK.json", payload)
    return 0


def cmd_measurement_lock(args: argparse.Namespace) -> int:
    calibration = committed_calibration(args.calibration_result, args.evidence_repo)
    payload = lock_payload(args, "MEASUREMENT", calibration=calibration)
    required = (
        "PRODUCT_SHA",
        "RECIPE_SHA256",
        "DATASET_SHA256",
        "ENV_FINGERPRINT_SHA256",
        "PROTOCOL_SHA256",
        "COMPARATOR_SHA256",
    )
    for key in required:
        if calibration.get(key) != payload[key]:
            raise ValueError(f"calibration binding drift: {key}")
    validate_lock({**payload, "_self_sha256": canonical_hash(payload)})
    atomic_new_json(args.out / "P_MEASUREMENT_LOCK.json", payload)
    return 0


def _source_fingerprint(product: Path) -> str:
    # The product SHA names all tracked source; the smaller runtime-specific
    # digest additionally detects a wrongly mounted worker checkout.
    digest = hashlib.sha256()
    for path in sorted((product / "relax" / "utils" / "straggler").glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _resources() -> dict[str, Any]:
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=index,uuid,memory.used,memory.total", "--format=csv,noheader,nounits"],
            text=True,
        )
        return {"nvidia_smi": [line.strip() for line in output.splitlines() if line.strip()]}
    except (OSError, subprocess.CalledProcessError):
        return {"nvidia_smi": "unavailable"}


def _validate_execution(args: argparse.Namespace, lock: dict[str, Any], names: list[str]) -> None:
    validate_lock(lock)
    expected = lock["ARM_ORDER"]
    if names != expected:
        raise ValueError("requested arms must equal the frozen stage order; no implicit resume")
    product = args.product.resolve()
    if require_clean_head(product) != lock["PRODUCT_SHA"]:
        raise ValueError("product SHA drift")
    for path_key, hash_key in (
        ("RECIPE_PATH", "RECIPE_SHA256"),
        ("DATASET_PATH", "DATASET_SHA256"),
        ("ENV_FINGERPRINT_PATH", "ENV_FINGERPRINT_SHA256"),
        ("PROTOCOL_PATH", "PROTOCOL_SHA256"),
        ("RUNNER_PATH", "RUNNER_SHA256"),
        ("COMPARATOR_PATH", "COMPARATOR_SHA256"),
    ):
        if sha256_file(Path(lock[path_key])) != lock[hash_key]:
            raise ValueError(f"frozen input drift: {path_key}")
    if int(lock["RECIPE_ENV"]["NUM_ROLLOUT"]) != lock["EXPECTED_STEPS"]:
        raise ValueError("locked step count differs from recipe environment")


def _preflight(product: Path, dashboard: str) -> None:
    subprocess.run(
        [sys.executable, str(product / "scripts" / "tools" / "ray_job_preflight.py"), "--address", dashboard],
        check=True,
        timeout=60,
    )


def _run_process(command: list[str], cwd: Path, env: dict[str, str], log: Path) -> None:
    with log.open("w") as output:
        process = subprocess.Popen(
            command, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            if process.wait(timeout=300):
                raise subprocess.CalledProcessError(process.returncode, command)
        except BaseException:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(process.pid, sig)
                    process.wait(timeout=10)
                    break
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    pass
            raise


def _worker_provenance(log: Path) -> dict[str, str]:
    text = log.read_text(errors="replace") if log.exists() else ""
    roots = sorted(set(re.findall(r"straggler provenance: relax_root=(\S+)", text)))
    result = {}
    for root in roots:
        source_root = Path(root).parent
        if source_root.exists():
            result[root] = _source_fingerprint(source_root)
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
    job_id = f"codex-c2p-{lock['PRODUCT_SHA'][:8]}-{args.out.name}-{name}"[:100]
    client = JobSubmissionClient(args.dashboard)
    if any(job.submission_id == job_id for job in client.list_jobs()):
        raise ValueError(f"owned submission ID already exists: {job_id}")
    env = dict(os.environ)
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
            "SAVE": "1",
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
        "recipe": lock["RECIPE_PATH"],
        "recipe_sha256": lock["RECIPE_SHA256"],
        "dataset_sha256": lock["DATASET_SHA256"],
        "env_fingerprint_sha256": lock["ENV_FINGERPRINT_SHA256"],
        "protocol_sha256": lock["PROTOCOL_SHA256"],
        "runner_sha256": lock["RUNNER_SHA256"],
        "comparator_sha256": lock["COMPARATOR_SHA256"],
        "expected_steps": lock["EXPECTED_STEPS"],
        "save": 1,
        "checkpoint_retained": True,
        "resources_before": before,
        "driver_source_sha256_before": source_before,
        "worker_source_hashes": {},
        "valid": False,
        "started_at": time.time(),
    }
    path = arm_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    try:
        # Same launcher discipline as trace_campaign_927c5de: the repository
        # entrypoint owns the flock/preflight/env setup and exports
        # RELAX_ENTRYPOINT_MODE, keeping the recipe away from local.sh's
        # full-local "pkill -9 python" fallback (which killed a runner on
        # 2026-09-29; see the overlap campaign's archived INVALID attempt).
        launcher = product / "scripts" / "entrypoint" / "ray-job.sh"
        if not launcher.is_file():
            raise RuntimeError(f"missing repository launcher: {launcher}")
        _run_process(["bash", str(launcher), str(lock["RECIPE_PATH"])], product, env, arm_dir / "submit.log")
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
        # A snapshot alone cannot prove that Ray has released the placement.
        # Re-run the repository's non-mutating preflight before admitting the
        # next arm; it fails closed if our four-GPU reservation persists.
        try:
            _preflight(product, args.dashboard)
            manifest["resources_returned"] = True
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            manifest["resource_release_error"] = str(exc)
            manifest["resources_returned"] = False
        manifest["resources_after"] = _resources()
        manifest["valid"] = (
            manifest["driver_source_sha256_before"] == manifest["driver_source_sha256_after"]
            and bool(manifest["worker_source_hashes"])
            and all(value == source_before for value in manifest["worker_source_hashes"].values())
            and (arm_dir / "checkpoints").is_dir()
        )
        if not manifest["valid"]:
            raise RuntimeError("arm provenance/checkpoint gate failed")
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
        ("runner_sha256", lock["RUNNER_SHA256"]),
        ("comparator_sha256", lock["COMPARATOR_SHA256"]),
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
    checkpoint = arm_dir / "checkpoints"
    if not checkpoint.is_dir() or not any(path.is_file() for path in checkpoint.rglob("*")):
        problems.append("retained checkpoint missing")
    if problems:
        raise ValueError(f"{arm_dir.name}: {', '.join(problems)}")
    return manifest


def _calibration_bundle(args: argparse.Namespace) -> int:
    lock_path = args.lock.resolve()
    lock = load_lock(lock_path)
    if lock["STAGE"] != "CALIBRATION":
        raise ValueError("calibration-bundle requires a calibration lock")
    lock_sha = sha256_file(lock_path)
    arms = {name: validate_arm(args.campaign / name, lock, lock_sha) for name in CALIBRATION_ARMS}
    comparator = Path(lock["COMPARATOR_PATH"])
    if sha256_file(comparator) != lock["COMPARATOR_SHA256"]:
        raise ValueError("comparator drift")
    payload = {
        "status": "READY_FOR_INVENTORY_EXPORT",
        "calibration_lock_sha256": lock_sha,
        "PRODUCT_SHA": lock["PRODUCT_SHA"],
        "RECIPE_SHA256": lock["RECIPE_SHA256"],
        "DATASET_SHA256": lock["DATASET_SHA256"],
        "ENV_FINGERPRINT_SHA256": lock["ENV_FINGERPRINT_SHA256"],
        "PROTOCOL_SHA256": lock["PROTOCOL_SHA256"],
        "COMPARATOR_SHA256": lock["COMPARATOR_SHA256"],
        "EXPECTED_STEPS": lock["EXPECTED_STEPS"],
        "arm_manifests": {name: sha256_file(args.campaign / name / "manifest.json") for name in arms},
        "checkpoint_roots": {name: str((args.campaign / name / "checkpoints").resolve()) for name in arms},
    }
    atomic_new_json(args.out, payload)
    return 0


def _measurement_result(args: argparse.Namespace) -> int:
    lock_path = args.lock.resolve()
    lock = load_lock(lock_path)
    if lock["STAGE"] != "MEASUREMENT":
        raise ValueError("measurement-result requires a measurement lock")
    if sha256_file(args.calibration_result) != lock["CALIBRATION_RESULT_SHA256"]:
        raise ValueError("measurement lock calibration binding mismatch")
    calibration = json.loads(args.calibration_result.read_text())
    if calibration.get("tolerance_table_sha256") != lock.get("TOLERANCE_TABLE_SHA256"):
        raise ValueError("measurement lock tolerance table mismatch")
    lock_sha = sha256_file(lock_path)
    for name in MEASUREMENT_ARMS:
        validate_arm(args.campaign / name, lock, lock_sha)
    if len(args.pair_manifest) != 2:
        raise ValueError("exactly two pair manifests are required")
    pair_ids = []
    for raw in args.pair_manifest:
        pair = json.loads(Path(raw).read_text())
        if pair.get("product_sha") != lock["PRODUCT_SHA"] or pair.get("protocol_sha256") != lock["PROTOCOL_SHA256"]:
            raise ValueError("pair manifest identity drift")
        if pair.get("calibration_sha256") != lock["CALIBRATION_RESULT_SHA256"]:
            raise ValueError("pair manifest calibration binding drift")
        if pair.get("measurement_lock_sha256") != lock_sha:
            raise ValueError("pair manifest measurement lock binding drift")
        pair_ids.append(pair.get("pair_id"))
    if pair_ids != ["P-M1", "P-M2"]:
        raise ValueError("pair manifests must be P-M1 then P-M2")
    from c2_parameter_verdict_927c5de import run as verdict_run

    return verdict_run(
        type(
            "Args",
            (),
            {
                "calibration": str(args.calibration_result),
                "pair_manifest": [str(x) for x in args.pair_manifest],
                "out": str(args.out),
            },
        )()
    )


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
    calibration_lock = sub.add_parser("calibration-lock")
    _lock_common_args(calibration_lock)
    calibration_lock.set_defaults(func=cmd_calibration_lock)
    measurement_lock = sub.add_parser("measurement-lock")
    _lock_common_args(measurement_lock)
    measurement_lock.add_argument("--calibration-result", type=Path, required=True)
    measurement_lock.add_argument("--evidence-repo", type=Path, required=True)
    measurement_lock.set_defaults(func=cmd_measurement_lock)
    calibration_result = sub.add_parser("calibration-bundle")
    calibration_result.add_argument("--lock", type=Path, required=True)
    calibration_result.add_argument("--campaign", type=Path, required=True)
    calibration_result.add_argument("--out", type=Path, required=True)
    calibration_result.set_defaults(func=_calibration_bundle)
    measurement_result = sub.add_parser("measurement-result")
    measurement_result.add_argument("--lock", type=Path, required=True)
    measurement_result.add_argument("--calibration-result", type=Path, required=True)
    measurement_result.add_argument("--campaign", type=Path, required=True)
    measurement_result.add_argument("--pair-manifest", action="append", type=Path, required=True)
    measurement_result.add_argument("--out", type=Path, required=True)
    measurement_result.set_defaults(func=_measurement_result)
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
