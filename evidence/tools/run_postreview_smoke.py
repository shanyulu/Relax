# Copyright (c) 2026 Relax Authors. All Rights Reserved.

"""Supervise three real-recipe smoke jobs; never clean foreign resources."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import time
from pathlib import Path

from extract_c2_native import parse_arm


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def source_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((root / "relax/utils/straggler").glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def preflight(args: argparse.Namespace) -> None:
    subprocess.run(
        [
            "python",
            str(args.product / "scripts/tools/ray_job_preflight.py"),
            "--address",
            args.dashboard,
        ],
        check=True,
        timeout=40,
    )


def submit(command: list, root: Path, env: dict, log: object) -> None:
    process = subprocess.Popen(
        command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
    )
    try:
        code = process.wait(timeout=180)
        if code:
            raise subprocess.CalledProcessError(code, command)
    except BaseException:
        # Only this new session is ours; never target a shared Ray worker group.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        # An exited shell is not proof that all of its upload children exited.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        raise


def arm(args: argparse.Namespace, name: str) -> None:
    from ray.job_submission import JobSubmissionClient

    if git(args.product, "rev-parse", "HEAD") != args.head or git(args.product, "status", "--porcelain"):
        raise RuntimeError("product must match the frozen clean revision")
    preflight(args)
    out = args.out / name
    out.mkdir()
    job_id = f"codex-t11-{args.head[:8]}-{args.out.name}-{name}"
    client = JobSubmissionClient(args.dashboard)
    if any(job.submission_id == job_id for job in client.list_jobs()):
        raise RuntimeError("submission ID already exists")
    env = dict(os.environ)
    env.pop("RELAX_ENTRYPOINT_MODE", None)
    for key in list(env):
        if key.startswith(("RELAX_STRAGGLER_", "RELAX_KERNEL_CACHE_")):
            del env[key]
    env.update(
        {
            "RELAX": str(args.product),
            "WORKING_DIR": str(args.product),
            "RAY_ADDRESS": args.dashboard,
            "TRAIN_RAY_ADDRESS": args.gcs,
            "TRAIN_VENV": args.venv,
            "MEGATRON": args.megatron,
            "PYTHONPATH": args.bridge,
            "PROMPT_SET": str(args.dataset),
            "RELAX_RAY_JOB_SAFE_SUBMIT": "1",
            "RELAX_GPU_LOCK_HELD": str(os.getpid()),
            "RELAX_GPU_LOCK_FILE": args.lock,
            "RAY_NO_WAIT": "1",
            "RAY_JOB_SUBMISSION_ID": job_id,
            "SAVE": "0",
            "NUM_ROLLOUT": "8",
            "GLOBAL_BATCH_SIZE": "32",
            "SAVE_DIR": str(out / "checkpoints"),
            "LOG_DIR": str(out / "submit-logs"),
            "EXP_NAME": name,
            "TENSORBOARD_DIR": str(out / "tensorboard"),
        }
    )
    enabled = name.endswith("on")
    if enabled:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        env.update(
            {
                "RELAX_STRAGGLER_ENABLE": "1",
                "RELAX_STRAGGLER_OUTPUT_DIR": str(out / "straggler"),
                "RELAX_STRAGGLER_COLLECTOR_ADDR": f"127.0.0.1:{port}",
                "RELAX_STRAGGLER_WINDOW_S": "5",
                "RELAX_STRAGGLER_WARMUP_WINDOWS": "2",
                "RELAX_STRAGGLER_REPORT_INTERVAL_S": "10",
            }
        )
    command = [
        "bash",
        "scripts/entrypoint/ray-job.sh",
        "scripts/training/sft/run-qwen3-0.6B-4xgpu-dp4-observer.sh",
        "--tb-project-name",
        str(out / "tensorboard"),
        "--tb-experiment-name",
        name,
    ]
    record = {
        "name": name,
        "job_id": job_id,
        "head": args.head,
        "command": command,
        "source_sha256_before": source_hash(args.product),
        "started_at": time.time(),
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "valid": False,
    }
    manifest = out / "manifest.json"
    manifest.write_text(json.dumps(record, indent=2) + "\n")
    submitted = False
    try:
        with (out / "submit.log").open("w") as log:
            submit(command, args.product, env, log)
        submitted = True
        deadline = time.monotonic() + 1200
        while time.monotonic() < deadline:
            status = str(client.get_job_status(job_id))
            (out / "job.log").write_text(client.get_job_logs(job_id))
            if status in {"SUCCEEDED", "FAILED", "STOPPED"}:
                break
            time.sleep(5)
        else:
            raise TimeoutError("owned job exceeded 1200 s")
        record["job_status"] = status
        record["native"] = parse_arm(out, expected_steps=8)
        record["source_sha256_after"] = source_hash(args.product)
        roots = sorted(set(re.findall(r"straggler provenance: relax_root=(\S+)", (out / "job.log").read_text())))
        record["worker_source_hashes"] = {root: source_hash(Path(root).parent) for root in roots}
        record["envelope_lines"] = sum(
            len(p.read_text().splitlines()) for p in out.glob("straggler/**/straggler_envelopes.jsonl")
        )
        record["valid"] = (
            status == "SUCCEEDED"
            and record["native"].get("native_valid", False)
            and record["source_sha256_before"] == record["source_sha256_after"]
            and bool(roots)
            and all(value == record["source_sha256_before"] for value in record["worker_source_hashes"].values())
            and (not enabled or record["envelope_lines"] > 0)
        )
        if not record["valid"]:
            raise RuntimeError("smoke gate failed; see manifest")
    except Exception as exc:
        record["error"] = str(exc)
        raise
    finally:
        try:
            # A submit timeout may still have created the named job. The ID was
            # absent before launch; only this ID is eligible for stop.
            status = str(client.get_job_status(job_id))
            if status not in {"SUCCEEDED", "FAILED", "STOPPED"}:
                client.stop_job(job_id)
                record["owned_job_stop_requested"] = True
            (out / "job.log").write_text(client.get_job_logs(job_id))
        except Exception as exc:
            record["final_status_error"] = str(exc)
        clean = False
        for _ in range(12):
            try:
                preflight(args)
                clean = True
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                time.sleep(5)
        record["resources_returned"] = clean
        record["valid"] = record["valid"] and clean
        record["submitted"] = submitted
        record["finished_at"] = time.time()
        manifest.write_text(json.dumps(record, indent=2) + "\n")
        if not clean:
            raise RuntimeError("resources remain; refusing further jobs, no global cleanup performed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("product", "dataset", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in ("head", "dashboard", "gcs", "venv", "megatron", "bridge", "lock"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()

    def interrupted(signum: int, frame: object) -> None:
        raise KeyboardInterrupt(f"signal {signum}: stop only the owned job")

    signal.signal(signal.SIGTERM, interrupted)
    if (
        hashlib.sha256(args.dataset.read_bytes()).hexdigest()
        != "44f9ddacd1e078d60d1a65d43dda76283b5ba68c6db7bbd54462126cd6a59428"
    ):
        parser.error("dataset does not match frozen smoke input")
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ[key] = ""
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "*"
    if args.out.exists():
        parser.error("output directory already exists; do not overwrite an attempt")
    args.out.mkdir(parents=True)
    with open(args.lock, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for name in ("SM1-off", "SM2-on", "SM3-off"):
            arm(args, name)


if __name__ == "__main__":
    main()
