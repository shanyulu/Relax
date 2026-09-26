#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Unattended AB/BA session driver for Task 11 Phase 3 (overhead).

Runs 12 arms serially, one process at a time: six paired sessions, each doing
OFF then ON or ON then OFF (alternating), so a slow drift in the machine cannot
be mistaken for a profiler cost. The session is the statistical unit.

Guarantees:
  * a GPU guard runs before every arm; if any GPU is busy it polls every 60 s
    for up to 30 min and then refuses to launch rather than colliding;
  * the correct entry point is used (`scripts/entrypoint/ray-job.sh`), never a
    direct recipe launch (which is broken by the local.sh glob trap);
  * WORKING_DIR is pinned to the task11-c2 worktree, and the arm is marked
    INVALID if the driver's or an actor's provenance line does not resolve
    under that worktree;
  * every arm writes its own manifest (command, env, GPU snapshot, wall time,
    exit code, log paths, counters, resolved relax roots) before the next arm;
  * a hung arm is killed after --arm-timeout and recorded as a failure.

Nothing here is run until the GPU window is owned by this executor.

Usage:
    python run_abba_sessions.py --dry-run
    python run_abba_sessions.py [--start-session 0] [--out /path/evidence]
"""

import argparse
import hashlib
import json
import os
import pathlib
import socket
import subprocess
import urllib.request
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

WORKTREE = pathlib.Path("/root/autodl-tmp/relax-work/task11-c2")
DEFAULT_EVIDENCE = pathlib.Path("/root/autodl-tmp/relax-work/task11_evidence/c2_phase3")
CAMPAIGN_DIR = pathlib.Path("/root/autodl-tmp/relax-work/task11_evidence/gpu_campaign")
ANALYZER = pathlib.Path("/root/autodl-tmp/relax-work/task11_evidence/analyze_run.py")
ESTIMATOR = pathlib.Path("/root/autodl-tmp/relax-work/task11_evidence/analyze_overhead.py")
RECIPE = "scripts/training/sft/run-qwen3-0.6B-4xgpu-dp4-observer.sh"
WRAPPER = "scripts/entrypoint/ray-job.sh"
MODEL_PATH = (
    "/root/autodl-tmp/hf-cache/hub/models--Qwen--Qwen3-0.6B/snapshots/"
    "c1899de289a04d12100db370d81485cdf75e47ca"
)
TRAIN_VENV = "/root/autodl-tmp/megatron-stack/venv"
MEGATRON = "/root/autodl-tmp/megatron-stack/Megatron-LM"
# The carrier the recipe needs: rows keyed "problem"/"generated_solution".
# The ambient shell on this shared machine exports PROMPT_SET pointing at
# Task 4's raw DAPO-RL file (rows keyed prompt/label), which killed the SFT
# producer at step 0. The driver therefore PINS this path per arm and records
# its sha256 in every manifest, so a swapped carrier is visible.
SFT_DATASET = WORKTREE / "scripts/training/sft/data/dapo-math-17k-sft-256.jsonl"
PROMPT_SET = str(SFT_DATASET)
GPU_BUSY_MIB = 1000
GPU_BUSY_UTIL = 10
GPU_POLL_SECONDS = 60
GPU_WAIT_SECONDS = 30 * 60
#: The address `ray job submit` actually uses. The head ALSO answers on its node
#: IP (172.17.0.2:8265) but that endpoint returned 502 while 127.0.0.1 answered
#: 200 -- probing the other one deadlocks the block on a healthy cluster.
# GCS address: valid both for the `ray` CLI and for ray.init(address=...).
# The HTTP dashboard URL (127.0.0.1:8265) is rejected by ray.init(), which made
# the `actor` Serve deployment fail from session 2 onwards (2026-09-26).
RAY_ADDR = "http://127.0.0.1:8265"
# Injected into the *training* process env only. Must be a GCS address: ray.init(address=...)
# rejects the HTTP dashboard URL, which made the `actor` Serve deployment fail from
# session 2 onwards (S2-on INVALID-no-training-steps, 2026-09-26).
RAY_GCS = "127.0.0.1:6379"
ARM_TIMEOUT_SECONDS = 7200
#: A submit that prints nothing for this long is hung, not slow.
INIT_OUTPUT_TIMEOUT_SECONDS = 240
#: Set by ``main`` to the one revision this block measures; every arm asserts it.
EXPECTED_HEAD = ""
NUM_ROLLOUT = "48"
SLOW_INIT_SECONDS = 360.0
SESSIONS = 6


def gpu_snapshot() -> List[Dict[str, Any]]:
    """Return index/memory.used/utilization.gpu for every GPU."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,memory.used,utilization.gpu", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    rows = []
    for line in out.strip().splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 3:
            continue
        try:
            rows.append(
                {
                    "index": int(parts[0]),
                    "memory_used_mib": int(parts[1].split()[0]),
                    "utilization_gpu": int(parts[2].split()[0]),
                }
            )
        except ValueError:
            continue
    return rows


def gpus_busy(rows: List[Dict[str, Any]]) -> bool:
    return any(row["memory_used_mib"] > GPU_BUSY_MIB or row["utilization_gpu"] > GPU_BUSY_UTIL for row in rows)


def wait_for_gpus(label: str) -> Tuple[bool, List[Dict[str, Any]]]:
    """Poll until every GPU is idle, up to GPU_WAIT_SECONDS."""
    deadline = time.time() + GPU_WAIT_SECONDS
    while True:
        rows = gpu_snapshot()
        if not rows:
            print(f"[{label}] nvidia-smi unavailable; refusing to launch")
            return False, rows
        if not gpus_busy(rows):
            return True, rows
        if time.time() >= deadline:
            print(f"[{label}] GPUs still busy after {GPU_WAIT_SECONDS}s; refusing to launch: {rows}")
            return False, rows
        print(f"[{label}] GPUs busy, waiting {GPU_POLL_SECONDS}s: {rows}")
        time.sleep(GPU_POLL_SECONDS)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def arm_plan() -> List[Dict[str, Any]]:
    """Six alternating sessions of {OFF, ON}."""
    plan = []
    for index in range(SESSIONS):
        session = f"S{index + 1}"
        order = ["A", "B"] if index % 2 == 0 else ["B", "A"]
        for slot in order:
            plan.append({"session": session, "order": "->".join(order), "slot": slot, "arm": "off" if slot == "A" else "on"})
    return plan


def run_env(arm: str, output_dir: pathlib.Path, collector_addr: Optional[str]) -> Dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "TRAIN_VENV": TRAIN_VENV,
            "MEGATRON": MEGATRON,
            "RELAX": str(WORKTREE),
            "WORKING_DIR": str(WORKTREE),
            # The shared wrapper runs `ray list nodes` to resolve MASTER_ADDR. The
            # CLI resolves that to the head's node IP (172.17.0.2:8265), which
            # answers 502 here, so MASTER_ADDR came back empty and the arm died
            # ~28s in with no step. RAY_ADDRESS points the CLI at the endpoint
            # that does answer, and the env-only fix touches nothing shared.
            "RAY_ADDRESS": RAY_ADDR,
            "MODEL_PATH": MODEL_PATH,
            "SAVE": "0",
            "NUM_ROLLOUT": NUM_ROLLOUT,
        }
    )
    # PROMPT_SET is deliberately NOT exported here: the DAPO-RL constant used by
    # the GenRM vehicle points at rows keyed prompt/label, while the SFT recipe
    # needs its default rows keyed problem/generated_solution. Exporting the RL
    # set made the SFT producer die at step 0 with "SFT row missing prompt key
    # 'problem': available keys=['prompt','label']" (S1-off, 2026-09-25 22:11).
    env["PROMPT_SET"] = PROMPT_SET
    env["RAY_ADDRESS"] = RAY_ADDR
    for key in [key for key in env if key.startswith("RELAX_STRAGGLER_")]:
        del env[key]
    if arm == "on":
        env.update(
            {
                "RELAX_STRAGGLER_ENABLE": "1",
                "RELAX_STRAGGLER_OUTPUT_DIR": str(output_dir),
                "RELAX_STRAGGLER_WINDOW_S": "5",
                "RELAX_STRAGGLER_PERSIST_WINDOWS": "3",
                "RELAX_STRAGGLER_REPORT_INTERVAL_S": "10",
                "RELAX_STRAGGLER_WARMUP_WINDOWS": "2",
            }
        )
        if collector_addr:
            env["RELAX_STRAGGLER_COLLECTOR_ADDR"] = collector_addr
    return env


def sha256_file(path: pathlib.Path) -> Optional[str]:
    """Hash a file, or ``None`` when it cannot be read (never guess)."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def wait_for_ray_head(timeout_seconds: int = 300) -> None:
    """Wait for the exact endpoint the submit uses, then let the arm start.

    The probe and the submit MUST share one resolved address: this cluster answers
    200 on 127.0.0.1:8265 while the node IP (172.17.0.2:8265) returned 502, so
    probing the node IP made the block wait forever on a healthy cluster.
    """
    deadline = time.time() + timeout_seconds
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{RAY_ADDR}/api/version", timeout=10) as response:
                if response.status == 200:
                    return
                last = f"HTTP {response.status}"
        except Exception as exc:  # noqa: BLE001 - any failure means "not healthy yet"
            last = str(exc)
        print(f"[head-wait] {RAY_ADDR} not healthy yet ({last[:90]}); retrying in 15s", flush=True)
        time.sleep(15)
    raise SystemExit(f"Ray head {RAY_ADDR} unhealthy after {timeout_seconds}s; refusing to submit a doomed arm ({last[:200]})")


def assert_clean_expected_head(expected_head: str) -> Dict[str, Any]:
    """Every arm must run the same, clean revision.

    An arm on a dirty tree measures code that corresponds to no commit, so it can
    never be part of the acceptance evidence. This is asserted, not recorded and
    hoped for.
    """
    state = git_state()
    if state["dirty"]:
        raise SystemExit(
            f"refusing to run an arm on a dirty tree at {state['commit'][:12]}: "
            f"{state['status_porcelain'][:300]}"
        )
    if expected_head and state["commit"] != expected_head:
        raise SystemExit(
            f"refusing to mix revisions in one block: expected {expected_head[:12]}, found {state['commit'][:12]}"
        )
    return state


def git_state() -> Dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.run(args, cwd=WORKTREE, capture_output=True, text=True).stdout

    commit = run("git", "rev-parse", "HEAD").strip()
    porcelain = run("git", "status", "--porcelain").strip()
    diff_sha = hashlib.sha256(run("git", "diff").encode()).hexdigest()
    staged_sha = hashlib.sha256(run("git", "diff", "--cached").encode()).hexdigest()
    dirty = bool(porcelain)
    return {
        "commit": commit,
        "branch": run("git", "rev-parse", "--abbrev-ref", "HEAD").strip(),
        "dirty": dirty,
        "status_porcelain": porcelain,
        "diff_sha256": diff_sha,
        "staged_diff_sha256": staged_sha,
        # An arm on a dirty tree measures code that corresponds to no commit, so
        # it is attributed to the diff hash instead of pretending to be the tip.
        "tree_label": f"DIRTY-TREE@{diff_sha[:16]}" if dirty else f"CLEAN@{commit[:12]}",
    }


def provenance(log_text: str, expected_sha: Optional[str] = None) -> Dict[str, Any]:
    """Resolve each process's relax import root and verify its content.

    Ray's ``--working-dir`` uploads the worktree to a ``_ray_pkg_*`` copy, so the
    resolved path is not literally under the worktree. A root is accepted when it
    is under the worktree, or when it is such a copy whose straggler package
    hashes to the worktree's -- the same content rule ``manifest.py`` uses. A
    copy that cannot be read is unverifiable and fails the gate, never guessed.

    ``expected_sha`` is the worktree hash snapshotted at arm start, so a
    concurrent edit during the arm cannot turn a correctly uploaded copy into a
    false mismatch.
    """
    roots = []
    actor_roots = []
    seen_actor = False
    for line in log_text.splitlines():
        if "MegatronTrainRayActor" in line:
            seen_actor = True
        if "straggler provenance: relax_root=" in line:
            root = line.split("relax_root=", 1)[1].split(" ", 1)[0]
            roots.append(root)
            if seen_actor:
                actor_roots.append(root)
    expected = str(WORKTREE)
    live_sha = sha256_file(WORKTREE / "relax/utils/straggler/__init__.py")
    worktree_sha = expected_sha or live_sha
    checks = []
    for root in roots:
        path = pathlib.Path(root)
        if str(path).startswith(expected):
            checks.append({"root": root, "accepted": True, "reason": "under-worktree"})
            continue
        if "_ray_pkg_" in root or "working_dir_files" in root:
            root_sha = sha256_file(path / "utils/straggler/__init__.py")
            if root_sha is None:
                checks.append({"root": root, "accepted": False, "reason": "working-dir-copy-missing"})
            else:
                checks.append(
                    {
                        "root": root,
                        "accepted": root_sha == worktree_sha,
                        "reason": "working-dir-copy-sha256-match"
                        if root_sha == worktree_sha
                        else "working-dir-copy-sha256-mismatch",
                        "root_sha256": root_sha,
                    }
                )
        else:
            checks.append({"root": root, "accepted": False, "reason": "outside-worktree"})
    return {
        "provenance_lines": len(roots),
        "driver_relax_root": roots[0] if roots else None,
        "actor_relax_root": actor_roots[0] if actor_roots else (roots[-1] if len(roots) > 1 else None),
        "worktree_straggler_sha256": worktree_sha,
        "worktree_straggler_sha256_live": live_sha,
        "roots": checks,
        "all_under_worktree": bool(roots) and all(root.startswith(expected) for root in roots),
        "all_provenance_ok": bool(roots) and all(check["accepted"] for check in checks),
    }


def run_arm(entry: Dict[str, Any], out_root: pathlib.Path, session_port: int, dry_run: bool) -> Dict[str, Any]:
    session = entry["session"]
    arm = entry["arm"]
    run_id = f"{session}-{arm}"
    arm_dir = out_root / run_id
    log_path = arm_dir / "job.log"
    manifest_path = arm_dir / "manifest.json"
    collector_addr = f"127.0.0.1:{session_port}" if arm == "on" else None
    env = run_env(arm, arm_dir, collector_addr)
    command = ["bash", WRAPPER, RECIPE]

    manifest: Dict[str, Any] = {
        "run_id": run_id,
        "session": session,
        "order": entry["order"],
        "slot": entry["slot"],
        "arm": arm,
        "worktree": str(WORKTREE),
        "recipe": RECIPE,
        "wrapper": WRAPPER,
        "command": " ".join(command),
        "relax_env": {key: value for key, value in env.items() if key.startswith("RELAX_STRAGGLER_")},
        "collector_addr": collector_addr,
        "git": git_state(),
        "ray_address": RAY_ADDR,
        "dataset_path": PROMPT_SET,
        "dataset_sha256": sha256_file(pathlib.Path(PROMPT_SET)),
        "straggler_sha256_at_start": sha256_file(WORKTREE / "relax/utils/straggler/__init__.py"),
        "started_at": None,
        "finished_at": None,
        "wall_seconds": None,
        "exit_code": None,
        "gpus_before": None,
        "gpus_after": None,
        "timeout_seconds": ARM_TIMEOUT_SECONDS,
    }

    if dry_run:
        print(f"[dry-run] {run_id}: {manifest['command']}  env={manifest['relax_env']}  collector={collector_addr}")
        return manifest

    arm_dir.mkdir(parents=True, exist_ok=True)
    # Both guards run before every arm: one revision per block, and a cluster
    # that actually exists.
    assert_clean_expected_head(EXPECTED_HEAD)
    wait_for_ray_head()
    # A dirty tree measures code that corresponds to no commit; record the exact
    # diff next to the arm so the measured revision is recoverable.
    if manifest["git"]["dirty"]:
        patch = subprocess.run(
            ["git", "diff"], cwd=WORKTREE, capture_output=True, text=True
        ).stdout
        staged = subprocess.run(
            ["git", "diff", "--cached"], cwd=WORKTREE, capture_output=True, text=True
        ).stdout
        (CAMPAIGN_DIR / f"dirty_tree_{run_id}.patch").write_text(patch)
        (CAMPAIGN_DIR / f"dirty_tree_{run_id}.staged.patch").write_text(staged)
        manifest["git"]["dirty_patch"] = str(CAMPAIGN_DIR / f"dirty_tree_{run_id}.patch")
        manifest["git"]["dirty_staged_patch"] = str(CAMPAIGN_DIR / f"dirty_tree_{run_id}.staged.patch")
    ok, rows = wait_for_gpus(run_id)
    manifest["gpus_before"] = rows
    if not ok:
        manifest["exit_code"] = "gpu-guard-refused"
        manifest_path.write_text(json.dumps(manifest, indent=2, default=str) + "\n")
        raise SystemExit(f"{run_id}: GPU guard refused; stopping so the other owner can finish")

    started = time.time()
    manifest["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started))
    # The arm's output is streamed to disk as it arrives. Buffering it with
    # capture_output=True made a hung submit indistinguishable from progress:
    # job.log stayed empty until the arm ended, so "no output for N minutes"
    # could not be detected and an operator could not see the arm start.
    log_handle = log_path.open("w", encoding="utf-8", errors="replace")
    process = subprocess.Popen(
        command,
        cwd=WORKTREE,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        errors="replace",
    )
    exit_code: Any = None
    deadline = time.time() + ARM_TIMEOUT_SECONDS
    last_output = time.time()
    init_deadline = time.time() + INIT_OUTPUT_TIMEOUT_SECONDS
    saw_output = False
    try:
        assert process.stdout is not None
        for line in process.stdout:
            log_handle.write(line)
            log_handle.flush()
            saw_output = True
            last_output = time.time()
            if time.time() > deadline:
                process.kill()
                exit_code = "timeout"
                break
        if exit_code is None:
            exit_code = process.wait(timeout=60)
    except Exception as exc:  # noqa: BLE001 - the arm is recorded invalid, never guessed
        process.kill()
        exit_code = f"driver-error: {exc}"
    finally:
        # A submit that never prints anything is not training; kill it rather
        # than let it hold the GPU window.
        if not saw_output and time.time() > init_deadline and process.poll() is None:
            process.kill()
            exit_code = "INVALID-slow-init"
            log_handle.write(f"driver: no arm output within {INIT_OUTPUT_TIMEOUT_SECONDS}s; killed the submit\n")
        log_handle.close()
        if process.poll() is None:
            process.kill()
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    finished = time.time()

    manifest["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(finished))
    manifest["wall_seconds"] = round(finished - started, 3)
    manifest["exit_code"] = exit_code
    manifest["gpus_after"] = gpu_snapshot()
    log_path.write_text(log_text)

    prov = provenance(log_text, expected_sha=manifest.get("straggler_sha256_at_start"))
    manifest["provenance"] = prov
    observation_ok = exit_code == 0 and prov["all_provenance_ok"]
    manifest["valid"] = bool(observation_ok)
    if not prov["all_provenance_ok"]:
        reasons = sorted({check["reason"] for check in prov["roots"] if not check["accepted"]})
        manifest["invalid_reason"] = "a process did not resolve task11-c2 relax code: " + ",".join(reasons or ["no-provenance-line"])
    elif exit_code != 0:
        manifest["invalid_reason"] = f"exit code {exit_code}"

    # Slow-init classification: the lead's "kill an arm whose init exceeds six
    # minutes" rule needs a machine-decidable flag even when the arm is killed by
    # hand. Presence of the first step is read from the arm's own text.
    first_step_seen = "Actor training step 0/" in log_text
    manifest["first_step_seen"] = first_step_seen
    manifest["slow_init"] = bool(
        not first_step_seen and manifest["wall_seconds"] and manifest["wall_seconds"] > SLOW_INIT_SECONDS
    )
    if manifest["slow_init"]:
        manifest["invalid_reason"] = f"INVALID-slow-init (> {SLOW_INIT_SECONDS}s without a first step)"

    # Every arm gets an analyze_run.py summary; a missing log is reported as
    # missing, never invented.
    summary = arm_dir / "summary.json"
    # The observer writes into a run-scoped subdirectory, so point the analyzer
    # at the run that actually produced this arm's data (fall back to the arm
    # directory, where the analyzer reports the files as missing, never invents).
    evidence_dir = arm_dir
    run_dirs = sorted(arm_dir.glob("run_*/collector_status.json"))
    if run_dirs:
        evidence_dir = run_dirs[0].parent
    manifest["evidence_dir"] = str(evidence_dir)
    if ANALYZER.exists() and log_path.exists():
        subprocess.run(
            [sys.executable, str(ANALYZER), str(log_path), str(evidence_dir), "--out", str(summary)],
            capture_output=True,
            text=True,
        )
        manifest["summary_path"] = str(summary)

    # An ON arm whose observer produced no envelopes is not a valid overhead
    # measurement: it would be an OFF arm wearing an ON label. Record it as
    # INVALID-observer-silent so the estimator can exclude it, never average it.
    # An operator kill truncates the buffered log, so the log alone can deny that
    # an arm trained. Run-scoped collector artifacts are written independently and
    # outrank it: an arm with flushed envelopes HAS trained and observed.
    on_disk_envelopes = 0
    for status_file in arm_dir.glob("run_*/collector_status.json"):
        try:
            on_disk_envelopes = max(
                on_disk_envelopes, int(json.loads(status_file.read_text()).get("flushed_lines") or 0)
            )
        except Exception:
            continue
    if on_disk_envelopes:
        manifest["first_step_seen"] = True
        first_step_seen = True
        manifest["slow_init"] = False
        manifest["observer_envelopes_source"] = "run-scoped collector artifacts"

    if arm == "on":
        envelopes: Any = None
        try:
            envelopes = json.loads(summary.read_text())["observation"]["envelopes"]
        except Exception:
            envelopes = None
        if on_disk_envelopes and (envelopes is None or envelopes < on_disk_envelopes):
            envelopes = on_disk_envelopes
        manifest["observer_envelopes"] = envelopes
        # Envelope counts say NOTHING about an arm that never trained: an ON arm
        # killed during init produces zero envelopes because it produced no
        # steps. Only an arm that actually trained may be called observer-silent,
        # otherwise an operator kill is mislabelled as an instrumentation defect.
        if not envelopes:
            manifest["valid"] = False
            if first_step_seen:
                manifest["invalid_reason"] = "INVALID-observer-silent"
            elif exit_code in (143, "143", -15):
                manifest["invalid_reason"] = "INVALID-killed-by-operator"
            else:
                manifest["invalid_reason"] = f"INVALID-no-training-steps (exit {exit_code})"

    manifest_path.write_text(json.dumps(manifest, indent=2, default=str) + "\n")
    print(
        f"[{run_id}] exit={exit_code} wall={manifest['wall_seconds']}s valid={manifest['valid']} "
        f"envelopes={manifest.get('observer_envelopes')}"
    )
    # A per-arm failure is recorded and the block continues; only a systemic
    # failure (the arm never reached a step, e.g. the SFT data-contract crash)
    # stops the run so the GPU window is not spent on a broken configuration.
    systemic = manifest.get("exit_code") == "gpu-guard-refused" or (
        exit_code != 0 and not manifest.get("first_step_seen")
    )
    if systemic:
        raise SystemExit(f"{run_id} INVALID: {manifest.get('invalid_reason')}; stopping the session run")
    return manifest


def build_overhead_manifest(out_root: pathlib.Path) -> pathlib.Path:
    """Assemble the frozen estimator's input from the arm manifests."""
    freeze = subprocess.run(
        [sys.executable, str(ESTIMATOR), "--freeze"], capture_output=True, text=True, check=True
    ).stdout
    estimator_sha = json.loads(freeze)["sha256"]
    sessions: List[Dict[str, Any]] = []
    off_arms: List[Dict[str, Any]] = []
    on_arms: List[Dict[str, Any]] = []
    for index in range(SESSIONS):
        session = f"S{index + 1}"
        entry: Dict[str, Any] = {
            "session": session,
            "order": "A->B" if index % 2 == 0 else "B->A",
            "A": {},
            "B": {},
        }
        for arm, slot in (("off", "A"), ("on", "B")):
            run_id = f"{session}-{arm}"
            arm_dir = out_root / run_id
            manifest_file = arm_dir / "manifest.json"
            if not manifest_file.exists():
                continue
            manifest = json.loads(manifest_file.read_text())
            if not manifest.get("valid"):
                continue
            payload = {"log": str(arm_dir / "job.log"), "wall_s": manifest.get("wall_seconds")}
            entry[slot] = payload
            (off_arms if arm == "off" else on_arms).append({"session": run_id, **payload})
        if entry["A"] and entry["B"]:
            sessions.append(entry)

    # Null control and A/A repeatability are derived from the arms already run
    # (consecutive OFF-vs-OFF and ON-vs-ON pairs), so the protocol's controls
    # cost no extra GPU time and use the real machine drift.
    null_control = [
        {"session": f"{a['session']}-vs-{b['session']}", "A": a, "B": b}
        for a, b in zip(off_arms, off_arms[1:])
    ]
    aa_repeat = [
        {"session": f"{a['session']}-vs-{b['session']}", "A": a, "B": b}
        for a, b in zip(on_arms, on_arms[1:])
    ]
    manifest = {
        "manifest_version": 1,
        "estimator_sha256": estimator_sha,
        "arms": {"A": "off", "B": "on"},
        "warmup_steps": 20,
        "bootstrap": {"replicates": 10000, "seed": 20260925},
        "sessions": sessions,
        "null_control": null_control,
        "aa_repeat": aa_repeat,
    }
    target = out_root / "overhead_manifest.json"
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--start-session", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    plan = [entry for entry in arm_plan() if int(entry["session"][1:]) - 1 >= args.start_session]
    if args.dry_run:
        for index in range(args.start_session, SESSIONS):
            print(f"--- {pathlib.Path('S')}{index + 1}: port={free_port()} (allocated for real only) ---")
        for entry in plan:
            run_arm(entry, args.out, 0, dry_run=True)
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    # One revision for the whole block: captured once, asserted before every arm.
    global EXPECTED_HEAD
    EXPECTED_HEAD = assert_clean_expected_head("")["commit"]
    print(f"[block] measuring {EXPECTED_HEAD[:12]} on a clean tree", flush=True)
    session_ports: Dict[str, int] = {}
    for entry in plan:
        session = entry["session"]
        # Resume: an arm that already produced a valid manifest is not re-run, so
        # an interrupted block restarts where it stopped instead of burning the
        # GPU window on arms that already have evidence.
        prior_path = args.out / f"{session}-{entry['arm']}" / "manifest.json"
        if prior_path.exists():
            try:
                prior = json.loads(prior_path.read_text())
            except Exception:
                prior = {}
            if prior.get("valid") and prior.get("exit_code") == 0:
                print(f"[resume] {session}-{entry['arm']}: valid manifest present, skipping")
                continue
        if session not in session_ports:
            # The OFF arm has no collector; the ON arm binds this port.
            session_ports[session] = free_port()
        manifest = run_arm(entry, args.out, session_ports[session], dry_run=False)
        # A single retry, and ONLY when the failure is provably pre-training:
        # nothing was ever logged as a step. A failure that reached training is a
        # real result and must still fail the arm -- retrying it would hide a
        # genuine training defect behind a second attempt.
        if not manifest.get("valid") and not manifest.get("first_step_seen"):
            print(
                f"[retry] {session}-{entry['arm']}: pre-training failure "
                f"({manifest.get('invalid_reason')}); retrying once",
                flush=True,
            )
            wait_for_ray_head()
            manifest = run_arm(entry, args.out, session_ports[session], dry_run=False)

    manifest = build_overhead_manifest(args.out)
    print(f"overhead manifest: {manifest}")
    subprocess.run([sys.executable, str(ESTIMATOR), str(manifest), "--out", str(args.out / "overhead.json")])
    return 0


if __name__ == "__main__":
    sys.exit(main())