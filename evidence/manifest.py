#!/usr/bin/env python3
"""Capture the provenance of one Task 11 observer arm.

Written because the first OFF arm silently ran TASK 4 code: the Ray daemons on
this host were started with cwd=/root/autodl-tmp/relax-work/task4-pr and, with
no runtime-env working_dir, both the job driver and every actor inherited that
cwd/PYTHONPATH, so `python -m relax.entrypoints.train` imported task4-pr/relax
(which has no relax/utils/straggler at all). Commit SHA alone does not catch
this -- the resolved module path does, so this tool records it for the driver
and for at least one actor, using py-spy to read the live interpreter's frame
file paths.

py-spy is used only as a bonus: this container lacks CAP_SYS_PTRACE, so the
authoritative check is deterministic import resolution -- the first entry of
[cwd] + PYTHONPATH (for `python -m`) or PYTHONPATH (for a Ray worker) that
contains relax/__init__.py -- plus a sha256 of that package's
relax/utils/straggler/__init__.py compared with the worktree's.

Usage:
    manifest.py --arm <name> --job <ray-submission-id> --log <path>
                --evidence <dir> --status <started|finished> --out <json>

Every probe is best-effort: a value that cannot be read is recorded as null
with the reason, never guessed.
"""

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import time

WORKTREE = "/root/autodl-tmp/relax-work/task11-c2"
ACTOR_MATCH = "MegatronTrainRayActor"
DRIVER_MATCH = "relax.entrypoints.train --resource"
RELAX_FRAME = re.compile(r"(/[^\s\"']*?/relax/[A-Za-z0-9_./-]+\.py)")
STRAGGLER_REL = "utils/straggler/__init__.py"


def sha256(path: str):
    try:
        return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
    except Exception:  # noqa: BLE001
        return None


def resolve_relax(cwd, pythonpath: str, is_driver: bool):
    """Emulate the interpreter's module search for the `relax` package.

    `python -m` puts the cwd first; a Ray worker resolves through PYTHONPATH.
    Returns the package root (the directory containing relax/) or None.
    """
    candidates = []
    if is_driver and cwd:
        candidates.append(cwd)
    if pythonpath:
        candidates.extend(p for p in pythonpath.split(":") if p)
    if not is_driver and cwd:
        # Worker script dir comes first in practice, but it holds no relax/.
        candidates.append(cwd)
    for entry in candidates:
        if pathlib.Path(entry, "relax", "__init__.py").is_file():
            return entry + "/relax"
    return None


def run(cmd: list) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    except Exception as exc:  # noqa: BLE001 - provenance is best-effort
        return f"<failed: {exc!r}>"


def pids_matching(pattern: str) -> list:
    out = run(["pgrep", "-f", pattern])
    pids = []
    for line in out.split():
        if line.isdigit():
            pids.append(int(line))
    return pids


def proc_cwd(pid: int):
    try:
        return str(pathlib.Path(f"/proc/{pid}/cwd").resolve())
    except Exception:  # noqa: BLE001
        return None


def proc_pythonpath(pid: int):
    try:
        raw = pathlib.Path(f"/proc/{pid}/environ").read_bytes()
    except Exception:  # noqa: BLE001
        return None
    for entry in raw.split(b"\0"):
        if entry.startswith(b"PYTHONPATH="):
            return entry.decode(errors="replace").split("=", 1)[1]
    return None


def relax_files_from_pyspy(pid: int) -> list:
    """Frame file paths mentioning /relax/ from a live-process stack dump."""
    dump = run(["py-spy", "dump", "--pid", str(pid)])
    return sorted({m for m in RELAX_FRAME.findall(dump)})


def relax_package_of(path: str):
    """Return the package root (the dir containing relax/) of a module path."""
    marker = "/relax/"
    if marker not in path:
        return None
    return path.split(marker)[0] + "/relax"


WORKTREE_STRAGGLER_SHA = sha256(f"{WORKTREE}/relax/{STRAGGLER_REL}")


def process_probe(pid: int, is_driver: bool = False) -> dict:
    cwd = proc_cwd(pid)
    pp = proc_pythonpath(pid)
    resolved = resolve_relax(cwd, pp, is_driver)
    digest = sha256(f"{resolved}/{STRAGGLER_REL}") if resolved else None
    frames = relax_files_from_pyspy(pid)
    is_copy = bool(resolved) and "working_dir_files" in resolved
    return {
        "pid": pid,
        "cwd": cwd,
        "pythonpath": pp,
        "resolved_relax": resolved,
        "resolved_is_task4pr": bool(resolved) and "relax-work/task4-pr" in resolved,
        "resolved_is_working_dir_copy": is_copy,
        "straggler_sha256": digest,
        "pyspy_frames": frames,
        "pyspy_available": bool(frames),
        # A working_dir copy is the uploaded snapshot of the worktree, so the
        # hash -- not the literal path -- decides identity.
        "resolved_under_task11_c2": bool(resolved)
        and (resolved.startswith(WORKTREE) or is_copy),
        "code_matches_worktree": digest is not None and digest == WORKTREE_STRAGGLER_SHA,
    }


def job_status(job_id: str):
    if not job_id:
        return None
    out = run(["ray", "job", "list"])
    for line in out.splitlines():
        if f"submission_id='{job_id}'" in line:
            status = re.search(r"status=<JobStatus\.(\w+)", line)
            message = re.search(r"message='([^']*)'", line)
            error = re.search(r"error_type='([^']*)'", line)
            return {
                "status": status.group(1) if status else None,
                "message": message.group(1) if message else None,
                "error_type": error.group(1) if error else None,
            }
    return "not_found"


def gpu_snapshot() -> dict:
    out = run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.used,memory.total,utilization.gpu",
            "--format=csv,noheader",
        ]
    )
    return {"raw": out.strip(), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", required=True)
    parser.add_argument("--job", default="")
    parser.add_argument("--log", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    head = run(["git", "-C", WORKTREE, "rev-parse", "HEAD"]).strip()
    running = [ln for ln in run(["ray", "job", "list"]).splitlines() if "RUNNING" in ln]
    # any RUNNING job other than this arm violates the exclusive window.
    other_running = []
    for line in running:
        sid = re.search(r"submission_id='([^']+)'", line)
        if sid and sid.group(1) != args.job:
            other_running.append(sid.group(1))

    driver_probes = []
    for pid in pids_matching(DRIVER_MATCH):
        cwd = proc_cwd(pid)
        if cwd and "working_dir_files" in cwd:
            driver_probes.append(process_probe(pid, is_driver=True))

    actor_probes = []
    for pid in pids_matching(ACTOR_MATCH):
        probe = process_probe(pid, is_driver=False)
        # Ignore stale workers from older worktrees.
        if (probe["cwd"] and WORKTREE in (probe["cwd"] or "")) or (
            probe["pythonpath"] and WORKTREE in (probe["pythonpath"] or "")
        ):
            actor_probes.append(probe)

    manifest = {
        "arm": args.arm,
        "phase": args.status,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "job_submission_id": args.job or None,
        "git_head": head,
        "log": args.log,
        "evidence_dir": args.evidence,
        "worktree": WORKTREE,
        "worktree_straggler_sha256": WORKTREE_STRAGGLER_SHA,
        "ran_alone": not other_running,
        "other_running_jobs": other_running,
        "driver": driver_probes,
        "actors": actor_probes,
        "driver_resolved_under_task11_c2": bool(driver_probes)
        and all(p["resolved_under_task11_c2"] for p in driver_probes),
        "actor_resolved_under_task11_c2": bool(actor_probes)
        and all(p["resolved_under_task11_c2"] for p in actor_probes),
        "driver_code_matches_worktree": bool(driver_probes)
        and all(p["code_matches_worktree"] for p in driver_probes),
        "actor_code_matches_worktree": bool(actor_probes)
        and all(p["code_matches_worktree"] for p in actor_probes),
        "any_probe_resolved_to_task4pr": any(
            p["resolved_is_task4pr"] for p in driver_probes + actor_probes
        ),
        "job": job_status(args.job) if args.job else None,
        "gpu": gpu_snapshot(),
    }
    manifest["valid_arm"] = bool(
        manifest["driver_resolved_under_task11_c2"]
        and manifest["actor_resolved_under_task11_c2"]
        and manifest["driver_code_matches_worktree"]
        and manifest["actor_code_matches_worktree"]
        and not manifest["any_probe_resolved_to_task4pr"]
    )

    # A capture taken after the job ends can see no live process. Keep the
    # probes from an earlier live capture instead of erasing the only
    # provenance we have.
    out_path = pathlib.Path(args.out)
    previous = {}
    if out_path.exists():
        try:
            previous = json.loads(out_path.read_text())
        except json.JSONDecodeError:
            previous = {}
    if previous:
        if not driver_probes and previous.get("driver"):
            manifest["driver"] = previous["driver"]
            manifest["driver_resolved_under_task11_c2"] = previous.get("driver_resolved_under_task11_c2")
            manifest["driver_code_matches_worktree"] = previous.get("driver_code_matches_worktree")
            manifest["probes_retained_from"] = previous.get("captured_at")
        if not actor_probes and previous.get("actors"):
            manifest["actors"] = previous["actors"]
            manifest["actor_resolved_under_task11_c2"] = previous.get("actor_resolved_under_task11_c2")
            manifest["actor_code_matches_worktree"] = previous.get("actor_code_matches_worktree")
            manifest["probes_retained_from"] = manifest.get("probes_retained_from") or previous.get("captured_at")
        manifest["valid_arm"] = bool(
            manifest["driver_resolved_under_task11_c2"]
            and manifest["actor_resolved_under_task11_c2"]
            and manifest["driver_code_matches_worktree"]
            and manifest["actor_code_matches_worktree"]
            and not manifest["any_probe_resolved_to_task4pr"]
        )

    out_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: manifest[k] for k in ("arm", "phase", "valid_arm", "ran_alone", "other_running_jobs")}))
    for label, probes in (("driver", driver_probes), ("actor", actor_probes)):
        for p in probes:
            print(
                f"  {label} pid={p['pid']} resolved={p['resolved_relax']} "
                f"under_c2={p['resolved_under_task11_c2']} sha_ok={p['code_matches_worktree']}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())