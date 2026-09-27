#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Two-stage C2 locking: calibration before any ON data is opened.

Stage 1  calibration-lock   freeze identity (product/recipe/dataset/env) and
                           the OFF arm order for the calibration population.
Stage 2  calibration-result read the OFF/OFF arms, decide the determinism
                           mode, compute the variability envelope, write a
                           sha-pinned C2_CALIBRATION_RESULT.json.
Stage 3  measurement-lock  freeze the REAL tolerances (referencing
                           CALIBRATION_RESULT_SHA256) plus the ON/OFF arm
                           order and measurement N. Only after this commit
                           may ON arms run / be read.
Stage 4  compare           validate measurement arms against the measurement
                           lock and apply the frozen tolerances.

Tolerance priority (frozen policy, from C2_PROTOCOL_A48A23B.md §2):
  1. exact deterministic equality  — if every OFF/OFF pairwise contrast is
     bit-identical (loss/grad/lr series AND checkpoint tree hashes), the
     measurement gate is exact equality.
  2. established numerical precision tolerance — not invoked by default;
     requires an independently justified bound recorded in the lock.
  3. OFF/OFF distribution envelope — tolerance = 2 x the maximum absolute
     pairwise delta observed over the ENTIRE calibration population (all
     pairwise contrasts x all steps). Statistical meaning (declared, not
     implied): the ON/OFF effect must stay within twice the worst-case
     same-build OFF/OFF noise; with 6 OFF arms this envelope uses 15 x 48 =
     720 delta samples. This is an envelope test, not a confidence
     interval, and is deliberately conservative vs any quantile.

No tolerance may be widened after ON data is seen; a wrong tolerance is a new
preregistration and the old result stands.
"""

import argparse
import hashlib
import itertools
import json
import subprocess
import sys
from pathlib import Path

from extract_c2_native import parse_arm


ENVELOPE_FACTOR = 2.0
CALIBRATION_ARMS = 6  # 3 OFF/OFF pairs; 15 pairwise contrasts x 48 steps


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def read_arm(arm_dir: Path, lock: dict) -> dict:
    manifest = json.loads((arm_dir / "manifest.json").read_text())
    problems = []
    git_info = manifest.get("git", {})
    if git_info.get("commit") != lock["PRODUCT_SHA"] or git_info.get("dirty"):
        problems.append("product drift/dirty")
    if manifest.get("dataset_sha256") != lock["DATASET_SHA256"]:
        problems.append("dataset drift")
    if manifest.get("recipe_sha256") != lock["RECIPE_SHA256"]:
        problems.append("recipe drift")
    if manifest.get("env_fingerprint_sha256") != lock["ENV_FINGERPRINT_SHA256"]:
        problems.append("env drift")
    if manifest.get("lock_sha256") != lock["_self_sha256"]:
        problems.append("lock reference drift")
    if manifest.get("expected_steps") != lock["EXPECTED_STEPS"]:
        problems.append("step-count drift")
    if problems:
        raise ValueError(f"{arm_dir.name}: {problems}")
    parsed = parse_arm(arm_dir, expected_steps=lock["EXPECTED_STEPS"])
    if not parsed.get("native_valid"):
        raise ValueError(f"{arm_dir.name}: native extraction invalid: {parsed.get('extraction_errors')}")
    # Checkpoints are hash-and-pruned by the runner (7.8G/arm does not fit the
    # disk): the durable record is the manifest's checkpoint_tree_sha256,
    # computed over the full tree before pruning. Recompute only if the
    # directory still exists AND the manifest does not carry a hash.
    ckpt = arm_dir / "checkpoints"
    manifest_hash = manifest.get("checkpoint_tree_sha256")
    if manifest_hash:
        parsed["checkpoint_tree_sha256"] = manifest_hash
    elif ckpt.exists():
        parsed["checkpoint_tree_sha256"] = tree_hash(ckpt)
    else:
        parsed["checkpoint_tree_sha256"] = None
    parsed["checkpoint_pruned_after_hash"] = bool(manifest.get("checkpoint_pruned_after_hash"))
    return parsed


def tree_hash(root: Path) -> str:
    """Hash of a checkpoint tree: sorted (relpath, filesize, file-sha)."""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = str(path.relative_to(root))
        digest.update(rel.encode())
        digest.update(str(path.stat().st_size).encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def cmd_calibration_lock(args: argparse.Namespace) -> int:
    product = Path(args.product)
    head = git(product, "rev-parse", "HEAD")
    if git(product, "status", "--porcelain"):
        raise SystemExit("product tree dirty; refusing to lock")
    arms = [f"C2C{i}-off" for i in range(1, CALIBRATION_ARMS + 1)]
    lock = {
        "PRODUCT_SHA": head,
        "RECIPE_PATH": str(Path(args.recipe)),
        "RECIPE_SHA256": sha256_file(Path(args.recipe)),
        "DATASET_PATH": str(Path(args.dataset)),
        "DATASET_SHA256": sha256_file(Path(args.dataset)),
        "ENV_FINGERPRINT_SHA256": sha256_file(Path(args.env)),
        "EXPECTED_STEPS": int(args.expected_steps),
        "ARM_ORDER": arms,
        "PROTOCOL_SHA256": sha256_file(Path(args.protocol)),
        "SAVE": 1,
        "PURPOSE": "OFF/OFF calibration only; no ON arm may reference this lock",
        "_self_sha256": None,
    }
    out = Path(args.out) / "C2_CALIBRATION_LOCK.json"
    if out.exists():
        raise SystemExit("refusing to overwrite an existing calibration lock")
    lock["_self_sha256"] = hashlib.sha256(json.dumps(lock, sort_keys=True).encode()).hexdigest()
    out.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out} (self-sha {lock['_self_sha256'][:12]})")
    return 0


def cmd_calibration_result(args: argparse.Namespace) -> int:
    lock = json.loads(Path(args.lock).read_text())
    root = Path(args.campaign)
    arms = [read_arm(root / name, lock) for name in lock["ARM_ORDER"]]
    names = lock["ARM_ORDER"]
    series_keys = ("loss_series", "grad_norm_series", "learning_rate_series", "token_series")
    contrasts = []
    deterministic = True
    for a, b in itertools.combinations(range(len(arms)), 2):
        entry = {"pair": f"{names[a]}/{names[b]}"}
        for key in series_keys:
            identical = arms[a][key] == arms[b][key]
            if not identical:
                deterministic = False
            cell = {"identical": identical}
            values = [v for v in (arms[a][key] + arms[b][key]) if isinstance(v, (int, float))]
            if not identical and values and len(values) == len(arms[a][key]) + len(arms[b][key]):
                deltas = [y - x for x, y in zip(arms[a][key], arms[b][key])]
                cell["max_abs_delta"] = max(map(abs, deltas)) if deltas else None
            # non-numeric series (learning-rate dicts) are equality-only
            entry[key] = cell
        ckpt_a = arms[a]["checkpoint_tree_sha256"]
        ckpt_b = arms[b]["checkpoint_tree_sha256"]
        entry["checkpoint_identical"] = ckpt_a is not None and ckpt_a == ckpt_b
        if not entry["checkpoint_identical"]:
            deterministic = False
        contrasts.append(entry)

    def envelope(key):
        vals = [
            c[key]["max_abs_delta"]
            for c in contrasts
            if isinstance(c.get(key), dict) and c[key].get("max_abs_delta") is not None
        ]
        return max(vals) if vals else None

    result = {
        "status": "FROZEN_OFF_ONLY",
        "lock_sha256_reference": sha256_file(Path(args.lock)),
        "PRODUCT_SHA": lock["PRODUCT_SHA"],
        "RECIPE_PATH": lock["RECIPE_PATH"],
        "RECIPE_SHA256": lock["RECIPE_SHA256"],
        "DATASET_SHA256": lock["DATASET_SHA256"],
        "ENV_FINGERPRINT_SHA256": lock["ENV_FINGERPRINT_SHA256"],
        "EXPECTED_STEPS": lock["EXPECTED_STEPS"],
        "deterministic": deterministic,
        "mode": "EXACT_EQUALITY" if deterministic else "OFF_OFF_ENVELOPE",
        "envelope_factor": ENVELOPE_FACTOR if not deterministic else None,
        "envelope_semantics": (
            "ON/OFF max |delta| must stay within 2x the worst OFF/OFF pairwise "
            "max |delta| over the whole calibration population (envelope test, "
            "not a confidence interval; deliberately conservative vs quantiles)"
        ),
        "calibration_population": {
            "arms": len(arms),
            "pairwise_contrasts": len(contrasts),
            "steps_per_series": lock["EXPECTED_STEPS"],
            "delta_samples_per_series": len(contrasts) * lock["EXPECTED_STEPS"],
        },
        "envelope": {key: envelope(key) for key in series_keys},
        "checkpoints": {n: a["checkpoint_tree_sha256"] for n, a in zip(names, arms)},
        "contrasts": contrasts,
        "tolerances": (
            {"mode": "EXACT_EQUALITY"}
            if deterministic
            else (
                {
                    "mode": "OFF_OFF_ENVELOPE_x2",
                    **{
                        key: (envelope(key) * ENVELOPE_FACTOR) if envelope(key) is not None else None
                        for key in series_keys
                    },
                }
            )
        ),
        "update_counts": {n: a["update_count"] for n, a in zip(names, arms)},
    }
    out = Path(args.out)
    if out.exists():
        raise SystemExit("refusing to overwrite an existing calibration result")
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"mode={result['mode']} result sha256 {sha256_file(out)}")
    print(f"tolerances: {json.dumps(result['tolerances'])[:300]}")
    return 0


def cmd_measurement_lock(args: argparse.Namespace) -> int:
    calib = json.loads(Path(args.calibration_result).read_text())
    if calib.get("status") != "FROZEN_OFF_ONLY":
        raise SystemExit("calibration result not frozen")
    if calib.get("mode") not in ("EXACT_EQUALITY", "OFF_OFF_ENVELOPE"):
        raise SystemExit("calibration mode missing")
    lock = {
        "CALIBRATION_RESULT_SHA256": sha256_file(Path(args.calibration_result)),
        "MEASUREMENT_N_PAIRS": int(args.n_pairs),
        "PRODUCT_SHA": calib.get("PRODUCT_SHA"),
        "RECIPE_PATH": calib.get("RECIPE_PATH"),
        "RECIPE_SHA256": calib.get("RECIPE_SHA256"),
        "DATASET_SHA256": calib.get("DATASET_SHA256"),
        "ENV_FINGERPRINT_SHA256": calib.get("ENV_FINGERPRINT_SHA256"),
        "EXPECTED_STEPS": calib.get("EXPECTED_STEPS", 48),
        "ARM_ORDER": [
            f"C2M{i}-{a}"
            for i in range(1, int(args.n_pairs) + 1)
            for a in (("off", "on") if i % 2 == 1 else ("on", "off"))
        ],
        "PRODUCT_SHA": calib.get("PRODUCT_SHA"),
        "GLOBAL_SYNC_RULE": "new_global_sync_count(ON vs OFF) == 0",
        "OVERLAP_DELTA_TOLERANCE": "frozen separately in TRACE_PROTOCOL per topology",
        "TOLERANCES": calib["tolerances"],
        "ENVELOPE_SEMANTICS": calib.get("envelope_semantics"),
        "_self_sha256": None,
    }
    out = Path(args.out) / "C2_MEASUREMENT_LOCK.json"
    if out.exists():
        raise SystemExit("refusing to overwrite an existing measurement lock")
    lock["_self_sha256"] = hashlib.sha256(json.dumps(lock, sort_keys=True).encode()).hexdigest()
    out.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out}; tolerances frozen from calibration {lock['CALIBRATION_RESULT_SHA256'][:12]}")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if out.exists():
        raise SystemExit("refusing to overwrite an existing comparison")
    lock = json.loads(Path(args.lock).read_text())
    calib = json.loads(Path(args.calibration_result).read_text())
    if lock["CALIBRATION_RESULT_SHA256"] != sha256_file(Path(args.calibration_result)):
        raise SystemExit("measurement lock does not reference this calibration result")
    root = Path(args.campaign)
    pairs = {}
    violations = []
    exact = lock["TOLERANCES"].get("mode") == "EXACT_EQUALITY"
    for i in range(1, lock["MEASUREMENT_N_PAIRS"] + 1):
        off = read_arm(
            root / f"C2M{i}-off",
            {
                **lock,
                "_self_sha256": lock["_self_sha256"],
                "DATASET_SHA256": calib.get("DATASET_SHA256", ""),
                "RECIPE_SHA256": calib.get("RECIPE_SHA256", ""),
                "ENV_FINGERPRINT_SHA256": calib.get("ENV_FINGERPRINT_SHA256", ""),
                "EXPECTED_STEPS": calib.get("steps_per_series", 48),
                "PRODUCT_SHA": lock["PRODUCT_SHA"],
            },
        )
        on = read_arm(
            root / f"C2M{i}-on",
            {
                **lock,
                "_self_sha256": lock["_self_sha256"],
                "DATASET_SHA256": calib.get("DATASET_SHA256", ""),
                "RECIPE_SHA256": calib.get("RECIPE_SHA256", ""),
                "ENV_FINGERPRINT_SHA256": calib.get("ENV_FINGERPRINT_SHA256", ""),
                "EXPECTED_STEPS": calib.get("steps_per_series", 48),
                "PRODUCT_SHA": lock["PRODUCT_SHA"],
            },
        )
        entry = {}
        lr_equal = off["learning_rate_series"] == on["learning_rate_series"]
        entry["learning_rate_series"] = {"exact_equal": lr_equal}
        if not lr_equal:
            violations.append(f"C2M{i}:learning_rate_series")
        for key in ("loss_series", "grad_norm_series", "token_series"):
            if exact:
                ok = off[key] == on[key]
                entry[key] = {"exact_equal": ok}
            else:
                deltas = [y - x for x, y in zip(off[key], on[key])]
                worst = max(map(abs, deltas))
                tol = lock["TOLERANCES"].get(key)
                # A None tolerance means OFF/OFF showed ZERO variability for this
                # series: the only consistent bound is exact equality.
                ok = (worst == 0.0) if tol is None else worst <= tol
                entry[key] = {"max_abs_delta": worst, "tolerance": tol, "within": ok}
            if not entry[key].get("exact_equal", entry[key].get("within", True)):
                violations.append(f"C2M{i}:{key}")
        if off["update_count"] != on["update_count"]:
            violations.append(f"C2M{i}:update_count")
        entry["checkpoint_exact_equal"] = (
            off["checkpoint_tree_sha256"] is not None and off["checkpoint_tree_sha256"] == on["checkpoint_tree_sha256"]
        )
        if exact and not entry["checkpoint_exact_equal"]:
            violations.append(f"C2M{i}:checkpoint")
        pairs[f"C2M{i}"] = entry
    verdict = "PASS" if not violations else "NOT_PASS"
    out.write_text(
        json.dumps(
            {
                "verdict": verdict,
                "violations": violations,
                "mode": lock["TOLERANCES"].get("mode"),
                "pairs": pairs,
                "measurement_lock_sha256": sha256_file(Path(args.lock)),
            },
            indent=2,
        )
        + "\n"
    )
    print(f"C2 measurement verdict: {verdict} ({len(violations)} violations)")
    return 0 if verdict == "PASS" else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    cl = sub.add_parser("calibration-lock")
    for name in ("product", "recipe", "dataset", "env", "out", "protocol"):
        cl.add_argument(f"--{name}", required=True)
    cl.add_argument("--expected-steps", type=int, required=True)
    cl.set_defaults(func=cmd_calibration_lock)
    cr = sub.add_parser("calibration-result")
    for name in ("lock", "campaign", "out"):
        cr.add_argument(f"--{name}", required=True)
    cr.set_defaults(func=cmd_calibration_result)
    ml = sub.add_parser("measurement-lock")
    for name in ("calibration-result", "out"):
        ml.add_argument(f"--{name}", required=True)
    ml.add_argument("--n-pairs", type=int, default=2)
    ml.set_defaults(func=cmd_measurement_lock)
    cm = sub.add_parser("compare")
    for name in ("lock", "calibration-result", "campaign", "out"):
        cm.add_argument(f"--{name}", required=True)
    cm.set_defaults(func=cmd_compare)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
