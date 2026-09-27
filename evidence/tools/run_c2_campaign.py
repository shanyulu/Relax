#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Supervised C2 campaign runner: calibration (OFF/OFF) and measurement arms.

Each arm runs the REAL observer recipe via the repository ray-job entrypoint
in safe mode with an owned submission ID, a 48-step SFT job and SAVE=1 (the
C2 protocol requires final checkpoints). The manifest records every identity
field the locks validate (product, recipe+sha, dataset, env fingerprint,
expected steps, pair order, analyzer/runner/protocol shas, lock self-sha),
so `campaign_lock`-style drift checks and `c2_lock.read_arm` both bind.

Never cleans foreign resources; on failure stops the OWNED submission only.
"""

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path

from extract_c2_native import parse_arm
from c2_lock import tree_hash

DATASET_SHA = "44f9ddacd1e078d60d1a65d43dda76283b5ba68c6db7bbd54462126cd6a59428"
ON_PROFILE = {
    "RELAX_STRAGGLER_ENABLE": "1",
    "RELAX_STRAGGLER_WINDOW_S": "5",
    "RELAX_STRAGGLER_WARMUP_WINDOWS": "2",
    "RELAX_STRAGGLER_REPORT_INTERVAL_S": "10",
}


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def source_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((root / "relax/utils/straggler").glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preflight(product: Path, dashboard: str) -> None:
    subprocess.run(
        ["python", str(product / "scripts/tools/ray_job_preflight.py"), "--address", dashboard],
        check=True,
        timeout=60,
    )


def submit(command, cwd: Path, env: dict, log) -> None:
    process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        code = process.wait(timeout=300)
        if code:
            raise subprocess.CalledProcessError(code, command)
    except BaseException:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
                break
            except subprocess.TimeoutExpired:
                continue
        raise


def run_arm(args, lock: dict, name: str) -> None:
    from ray.job_submission import JobSubmissionClient

    if git(args.product, "rev-parse", "HEAD") != args.head or git(args.product, "status", "--porcelain"):
        raise RuntimeError("product must stay at the frozen clean revision")
    preflight(args.product, args.dashboard)
    out = args.out / name
    out.mkdir()
    job_id = f"codex-t11-c2-{args.head[:8]}-{args.out.name}{args.job_tag}-{name}"
    client = JobSubmissionClient(args.dashboard)
    if any(job.submission_id == job_id for job in client.list_jobs()):
        raise RuntimeError("submission ID already exists")
    env = dict(os.environ)
    env.pop("RELAX_ENTRYPOINT_MODE", None)
    for key in list(env):
        if key.startswith(("RELAX_STRAGGLER_", "RELAX_KERNEL_CACHE_")):
            del env[key]
    arm_kind = name.rsplit("-", 1)[1]
    enabled = arm_kind == "on"
    if enabled:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        env.update(
            {
                "RELAX_STRAGGLER_OUTPUT_DIR": str(out / "straggler"),
                "RELAX_STRAGGLER_COLLECTOR_ADDR": f"127.0.0.1:{port}",
                **ON_PROFILE,
            }
        )
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
            "SAVE": "1",
            "NUM_ROLLOUT": "48",
            "GLOBAL_BATCH_SIZE": "32",
            "SAVE_DIR": str(out / "checkpoints"),
            "LOG_DIR": str(out / "submit-logs"),
            "EXP_NAME": name,
            "TENSORBOARD_DIR": str(out / "tensorboard"),
        }
    )
    for kv in (args.extra_env or []):
        key, _, value = kv.partition("=")
        env[key] = value
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env[key] = ""
    env["NO_PROXY"] = env["no_proxy"] = "*"
    command = [
        "bash",
        "scripts/entrypoint/ray-job.sh",
        "scripts/training/sft/run-qwen3-0.6B-4xgpu-dp4-observer.sh",
    ] + (args.recipe_args or [])
    record = {
        "run_id": name,
        "recipe_args": args.recipe_args or [],
        "session": name.rsplit("-", 1)[0],
        "arm": arm_kind,
        "order": "A->B" if int(re.sub(r"\D", "", name.rsplit("-", 1)[0])) % 2 == 1 else "B->A",
        "job_id": job_id,
        "pr_head": lock.get("PRODUCT_SHA") or lock.get("PR_HEAD"),
        "head": args.head,
        "git": {
            "commit": git(args.product, "rev-parse", "HEAD"),
            "dirty": bool(git(args.product, "status", "--porcelain")),
            "tree_label": f"CLEAN@{args.head[:8]}",
        },
        "command": command,
        "recipe": lock.get("RECIPE_PATH"),
        "recipe_sha256": lock.get("RECIPE_SHA256"),
        "dataset_sha256": sha256_file(Path(args.dataset)),
        "env_fingerprint_sha256": lock.get("ENV_FINGERPRINT_SHA256"),
        "expected_steps": lock.get("EXPECTED_STEPS", 48),
        "analyzer_sha256": lock.get("ANALYZER_SHA"),
        "runner_sha256": sha256_file(Path(__file__)),
        "protocol_sha256": lock.get("PROTOCOL_SHA256"),
        "lock_sha256": lock.get("_self_sha256") or lock.get("_lock_self_sha256"),
        "source_sha256_before": source_hash(args.product),
        "started_at": time.time(),
        "relax_env": {k: v for k, v in env.items() if k.startswith("RELAX_STRAGGLER_")},
        "valid": False,
    }
    manifest = out / "manifest.json"
    manifest.write_text(json.dumps(record, indent=2) + "\n")
    try:
        with (out / "submit.log").open("w") as log:
            submit(command, args.product, env, log)
        deadline = time.monotonic() + 1500
        status = "RUNNING"
        while time.monotonic() < deadline:
            status = str(client.get_job_status(job_id))
            (out / "job.log").write_text(client.get_job_logs(job_id))
            if status in {"SUCCEEDED", "FAILED", "STOPPED"}:
                break
            time.sleep(5)
        else:
            raise TimeoutError("owned job exceeded 1500 s")
        record["job_status"] = status
        record["native"] = parse_arm(out, expected_steps=record["expected_steps"])
        record["source_sha256_after"] = source_hash(args.product)
        roots = sorted(set(re.findall(r"straggler provenance: relax_root=(\S+)", (out / "job.log").read_text())))
        record["worker_source_hashes"] = {root: source_hash(Path(root).parent) for root in roots}
        record["envelope_lines"] = sum(
            len(p.read_text().splitlines()) for p in out.glob("straggler/**/straggler_envelopes.jsonl")
        )
        ckpt_dir = out / "checkpoints"
        if record["native"].get("native_valid", False) and ckpt_dir.exists():
            record["checkpoint_tree_sha256"] = tree_hash(ckpt_dir)
            record["checkpoint_pruned_after_hash"] = True
            shutil.rmtree(ckpt_dir)
        record["valid"] = (
            status == "SUCCEEDED"
            and record["native"].get("native_valid", False)
            and record["source_sha256_before"] == record["source_sha256_after"]
            and all(v == record["source_sha256_before"] for v in record["worker_source_hashes"].values())
            and (not enabled or record["envelope_lines"] > 0)
        )
        if not record["valid"]:
            raise RuntimeError("arm gate failed; see manifest")
    except Exception as exc:
        record["error"] = str(exc)
        raise
    finally:
        try:
            status_now = str(client.get_job_status(job_id))
            if status_now not in {"SUCCEEDED", "FAILED", "STOPPED"}:
                client.stop_job(job_id)
                record["owned_job_stop_requested"] = True
            (out / "job.log").write_text(client.get_job_logs(job_id))
        except Exception as exc:
            record["final_status_error"] = str(exc)
        clean = False
        for _ in range(12):
            try:
                preflight(args.product, args.dashboard)
                clean = True
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                time.sleep(5)
        record["resources_returned"] = clean
        record["valid"] = record["valid"] and clean
        record["finished_at"] = time.time()
        manifest.write_text(json.dumps(record, indent=2) + "\n")
        if not clean:
            raise RuntimeError("resources remain; refusing further arms, no global cleanup performed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("product", "dataset", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in ("head", "dashboard", "gcs", "venv", "megatron", "bridge", "gpulock"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--lock", type=Path, required=True, help="C2 calibration/measurement lock JSON")
    parser.add_argument("--arms", required=True, help="comma-separated arm names")
    parser.add_argument("--recipe-args", nargs="*", default=None, help="appended to the recipe (e.g. trace/overlap flags)")
    parser.add_argument("--job-tag", default="", help="appended to the job submission id namespace (Ray IDs are immutable)")
    parser.add_argument("--extra-env", nargs="*", default=None, help="KEY=VALUE env overrides applied last (e.g. C3 debug injection)")
    args = parser.parse_args()

    def interrupted(signum: int, frame: object) -> None:
        raise KeyboardInterrupt(f"signal {signum}: stop only the owned job")

    signal.signal(signal.SIGTERM, interrupted)
    if sha256_file(args.dataset) != DATASET_SHA:
        parser.error("dataset does not match the frozen C2 input")
    lock = json.loads(args.lock.read_text())
    if args.out.exists():
        for name in [a.strip() for a in args.arms.split(",") if a.strip()]:
            if (args.out / name).exists():
                parser.error(f"arm directory already exists: {name}; do not overwrite an attempt")
    else:
        args.out.mkdir(parents=True)
    with open(args.gpulock, "a") as lockfile:
        fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for name in [a.strip() for a in args.arms.split(",") if a.strip()]:
            run_arm(args, lock, name)
            print(f"[c2] {name}: done", flush=True)


if __name__ == "__main__":
    main()
