# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""CAMPAIGN_LOCK generator/validator for formal Task 11 acceptance runs.

A CAMPAIGN_LOCK freezes EVERY identity input of a formal campaign before the
first arm launches. Every arm manifest must reference the lock's sha256, and
any product change closes the namespace (a new lock, a new campaign root).

Usage:
  # generate (writes CAMPAIGN_LOCK.json; refuses to overwrite):
  python campaign_lock.py generate --product <worktree> --out <dir> \
      [--analyzer <path>] [--runner <path>] [--protocol <path>]

  # validate an arm directory against a lock:
  python campaign_lock.py validate --lock <CAMPAIGN_LOCK.json> --arm <arm-dir>

Rules encoded here (not left to discipline):
  - PRODUCT_SHA must be the exact 40-char HEAD of a CLEAN tree (no dirty, no
    staged diff, no unstaged diff). "or later" pins are structurally
    impossible: the lock stores one sha.
  - RECIPE_SHA256 / DATASET_SHA256 are content hashes of real files.
  - The PR head must equal the product sha when the campaign runs on the PR
    branch (recorded, not enforced here — the branch head can legitimately
    move after the campaign; manifests freeze what actually ran).
  - validate(): recomputes every hash the arm claims and refuses any drift,
    including RELAX_STRAGGLER_* settings that differ from the lock's ON-arm
    profile.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REQUIRED_KEYS = (
    "PRODUCT_SHA",
    "PR_HEAD",
    "ANALYZER_SHA",
    "RUNNER_SHA",
    "PROTOCOL_SHA",
    "RECIPE_SHA256",
    "DATASET_SHA256",
    "ENV_FINGERPRINT_SHA256",
    "EXPECTED_STEPS",
    "PAIR_ORDER",
    "BOOTSTRAP_SEED",
    "PRIMARY_METRIC",
    "ACCEPTANCE_RULE",
    "TRACE_BACKEND",
    "C2_TOLERANCES",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def generate(args: argparse.Namespace) -> int:
    product = Path(args.product)
    head = git(product, "rev-parse", "HEAD")
    if len(head) != 40:
        raise SystemExit(f"malformed HEAD: {head}")
    porcelain = git(product, "status", "--porcelain")
    if porcelain:
        raise SystemExit(f"product tree is dirty; refusing to lock:\n{porcelain}")
    recipe = Path(args.recipe)
    dataset = Path(args.dataset)
    out = Path(args.out)
    lock = {
        "PRODUCT_SHA": head,
        "PR_HEAD": head,
        "ANALYZER_SHA": sha256_file(Path(args.analyzer)),
        "RUNNER_SHA": sha256_file(Path(args.runner)),
        "PROTOCOL_SHA": sha256_file(Path(args.protocol)),
        "RECIPE_PATH": str(recipe),
        "RECIPE_SHA256": sha256_file(recipe),
        "DATASET_PATH": str(dataset),
        "DATASET_SHA256": sha256_file(dataset),
        "ENV_FINGERPRINT_SHA256": sha256_file(Path(args.env)),
        "EXPECTED_STEPS": int(args.expected_steps),
        "PAIR_ORDER": args.pair_order.split(","),
        "BOOTSTRAP_SEED": int(args.bootstrap_seed),
        "PRIMARY_METRIC": args.primary_metric,
        "ACCEPTANCE_RULE": (
            "PASS iff session-level whole-run mean estimate < 0.5% AND "
            "session-aware pair-level bootstrap 95% CI upper bound < 0.5%; "
            "median-only and steady-state-only never yield PASS; N=1 yields "
            "INCONCLUSIVE with a conditional point estimate only"
        ),
        "TRACE_BACKEND": args.trace_backend,
        "C2_TOLERANCES": (
            "frozen in C2_PROTOCOL before any ON data; OFF/OFF calibration "
            "precedes ON extraction; see referenced protocol file"
        ),
        "ON_ARM_PROFILE": {
            "RELAX_STRAGGLER_ENABLE": "1",
            "RELAX_STRAGGLER_WINDOW_S": "5",
            "RELAX_STRAGGLER_WARMUP_WINDOWS": "2",
            "RELAX_STRAGGLER_REPORT_INTERVAL_S": "10",
        },
    }
    missing = [k for k in REQUIRED_KEYS if k not in lock or lock[k] in (None, "")]
    if missing:
        raise SystemExit(f"lock incomplete: {missing}")
    target = out / "CAMPAIGN_LOCK.json"
    if target.exists():
        raise SystemExit("refusing to overwrite an existing CAMPAIGN_LOCK.json")
    target.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
    print(f"locked product {head[:8]}; lock sha256 {sha256_file(target)}")
    print(f"wrote {target}")
    return 0


def validate(args: argparse.Namespace) -> int:
    lock = json.loads(Path(args.lock).read_text())
    manifest = json.loads(Path(args.arm, "manifest.json").read_text())
    problems = []
    git_info = manifest.get("git", {})
    if git_info.get("commit") != lock["PRODUCT_SHA"]:
        problems.append(
            f"product sha {git_info.get('commit')} != locked {lock['PRODUCT_SHA']}"
        )
    if git_info.get("dirty"):
        problems.append("arm ran on a dirty tree")
    if manifest.get("dataset_sha256") != lock["DATASET_SHA256"]:
        problems.append("dataset sha drift")
    recipe = manifest.get("recipe")
    if recipe != manifest.get("recipe") or not recipe:
        problems.append("recipe missing")
    relax_env = manifest.get("relax_env", {})
    is_on = manifest.get("arm") == "on" or str(manifest.get("run_id", "")).endswith("-on")
    if is_on:
        for key, value in lock["ON_ARM_PROFILE"].items():
            if str(relax_env.get(key)) != value:
                problems.append(f"ON-arm env drift: {key}={relax_env.get(key)!r} != {value!r}")
    if manifest.get("lock_sha256") != sha256_file(Path(args.lock)):
        problems.append("manifest does not reference this lock (lock_sha256 mismatch)")
    if problems:
        print("INVALID:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"VALID {manifest.get('run_id') or manifest.get('name')}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--product", required=True)
    gen.add_argument("--out", required=True)
    gen.add_argument("--analyzer", required=True)
    gen.add_argument("--runner", required=True)
    gen.add_argument("--protocol", required=True)
    gen.add_argument("--recipe", required=True)
    gen.add_argument("--dataset", required=True)
    gen.add_argument("--env", required=True)
    gen.add_argument("--expected-steps", type=int, required=True)
    gen.add_argument("--pair-order", required=True, help="comma list, e.g. S1-off,S1-on,...")
    gen.add_argument("--bootstrap-seed", type=int, default=20260926)
    gen.add_argument("--primary-metric", default="perf/train_time")
    gen.add_argument("--trace-backend", default="torch.profiler(Kineto/CUPTI)")
    gen.set_defaults(func=generate)
    val = sub.add_parser("validate")
    val.add_argument("--lock", required=True)
    val.add_argument("--arm", required=True)
    val.set_defaults(func=validate)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
