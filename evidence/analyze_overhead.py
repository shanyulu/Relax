#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Frozen Phase-3 overhead estimator for Task 11 (AB/BA paired sessions).

This estimator is frozen BEFORE any acceptance run. Session is the statistical
unit: per-step values are resampled only inside their own session, sessions are
resampled across the arm pairs. Steps are never treated as independent.

Input: a JSON manifest, produced per session by ``analyze_run.py`` plus the raw
per-step ``perf/step_time`` series parsed from each job log:

    {
      "manifest_version": 1,
      "estimator_sha256": "<this file's sha256, recorded by --freeze>",
      "arms": {"A": "off", "B": "on"},
      "warmup_steps": 20,
      "bootstrap": {"replicates": 10000, "seed": 20260925},
      "sessions": [
        {"session": "S1", "order": "A->B", "A": {"log": "...", "wall_s": 123.4},
                                            "B": {"log": "...", "wall_s": 124.0}},
        ...
      ],
      "null_control": [{"session": "N1", "A": {...}, "B": {...}}],   # off vs off
      "aa_repeat":    [{"session": "P1", "A": {...}, "B": {...}}]    # same arm twice
    }

Every number is computed from the raw arrays; a missing log is reported as
missing, never substituted.

Usage:
    python analyze_overhead.py manifest.json [--out overhead.json]
    python analyze_overhead.py --selftest
"""

import argparse
import hashlib
import json
import pathlib
import random
import re
import statistics
import sys
from typing import Any, Dict, List, Optional, Tuple

STEP_TIME_RE = re.compile(r"'perf/step_time':\s*([0-9.eE+-]+)")

BOOTSTRAP_REPLICATES = 10000
BOOTSTRAP_SEED = 20260925
WARMUP_STEPS = 20
ACCEPTANCE_BOUND = 0.005  # +0.5 %


def parse_step_times(log_path: pathlib.Path) -> List[float]:
    """Return every ``perf/step_time`` value in log order."""
    if not str(log_path) or not log_path.is_file():
        return []
    text = log_path.read_text(errors="replace")
    values: List[float] = []
    for raw in STEP_TIME_RE.findall(text):
        try:
            values.append(float(raw))
        except ValueError:
            continue
    return values


def steady_state(values: List[float], warmup: int) -> List[float]:
    """Drop the warm-up steps but keep the rest in order."""
    return values[warmup:] if len(values) > warmup else []


def _ratio(numerator: List[float], denominator: List[float], statistic: str) -> Optional[float]:
    if not numerator or not denominator:
        return None
    if statistic == "median":
        num, den = statistics.median(numerator), statistics.median(denominator)
    else:
        num, den = statistics.fmean(numerator), statistics.fmean(denominator)
    if den == 0.0:
        return None
    return num / den - 1.0


def _percentile(ordered: List[float], fraction: float) -> float:
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def hierarchical_bootstrap(
    pairs: List[Tuple[List[float], List[float]]],
    statistic: str,
    replicates: int,
    rng: random.Random,
) -> Optional[Dict[str, float]]:
    """Paired session-level bootstrap with within-session step resampling.

    ``pairs`` is one ``(arm_a_steps, arm_b_steps)`` tuple per session. Each
    replicate resamples sessions with replacement, then resamples each arm's
    steps inside the resampled session, and aggregates the per-session ratios
    with the session-level statistic. The interval is the 2.5/97.5 percentile.
    """
    usable = [(a, b) for a, b in pairs if a and b]
    if len(usable) < 1:
        return None
    # Pairs are (A=off, B=on); the protocol's statistic is ON/OFF - 1.
    observed = [_ratio(b, a, statistic) for a, b in usable]
    observed = [value for value in observed if value is not None]
    if not observed:
        return None
    if statistic == "median":
        point = statistics.median(observed)
    else:
        point = statistics.fmean(observed)

    draws: List[float] = []
    for _ in range(replicates):
        sampled_sessions = [usable[rng.randrange(len(usable))] for _ in usable]
        per_session: List[float] = []
        for a, b in sampled_sessions:
            a_resampled = [a[rng.randrange(len(a))] for _ in a]
            b_resampled = [b[rng.randrange(len(b))] for _ in b]
            value = _ratio(b_resampled, a_resampled, statistic)
            if value is not None:
                per_session.append(value)
        if per_session:
            draws.append(statistics.median(per_session) if statistic == "median" else statistics.fmean(per_session))
    if not draws:
        return None
    draws.sort()
    return {
        "point": point,
        "lower": _percentile(draws, 0.025),
        "upper": _percentile(draws, 0.975),
        "n_sessions": len(usable),
        "n_replicates": len(draws),
    }


def _arm_steps(arm: Dict[str, Any], warmup: int) -> List[float]:
    """Inline ``steps`` (tests/programmatic) or a job ``log`` to parse."""
    inline = arm.get("steps")
    if isinstance(inline, list):
        return steady_state([float(value) for value in inline], warmup)
    return steady_state(parse_step_times(pathlib.Path(str(arm.get("log", "")))), warmup)


def _session_values(entry: Dict[str, Any], warmup: int) -> Tuple[List[float], List[float], Dict[str, Any]]:
    a_steps = _arm_steps(entry.get("A", {}), warmup)
    b_steps = _arm_steps(entry.get("B", {}), warmup)
    meta = {
        "session": entry.get("session"),
        "order": entry.get("order"),
        "A_wall_s": entry.get("A", {}).get("wall_s"),
        "B_wall_s": entry.get("B", {}).get("wall_s"),
        "A_steps": len(a_steps),
        "B_steps": len(b_steps),
        "A_p50": statistics.median(a_steps) if a_steps else None,
        "B_p50": statistics.median(b_steps) if b_steps else None,
    }
    return a_steps, b_steps, meta


def analyse(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Compute the full decision bundle from one manifest."""
    warmup = int(manifest.get("warmup_steps", WARMUP_STEPS))
    replicates = int(manifest.get("bootstrap", {}).get("replicates", BOOTSTRAP_REPLICATES))
    seed = int(manifest.get("bootstrap", {}).get("seed", BOOTSTRAP_SEED))

    result: Dict[str, Any] = {
        "manifest_version": manifest.get("manifest_version"),
        "arms": manifest.get("arms"),
        "warmup_steps": warmup,
        "bootstrap": {"replicates": replicates, "seed": seed},
        "acceptance_bound": ACCEPTANCE_BOUND,
        "sessions": [],
    }

    pairs: List[Tuple[List[float], List[float]]] = []
    for entry in manifest.get("sessions", []):
        a_steps, b_steps, meta = _session_values(entry, warmup)
        pairs.append((a_steps, b_steps))
        result["sessions"].append(meta)

    rng = random.Random(seed)
    result["median_ratio"] = hierarchical_bootstrap(pairs, "median", replicates, rng)
    result["mean_ratio"] = hierarchical_bootstrap(pairs, "mean", replicates, rng)

    # Whole-run wall time paired deltas.
    wall_deltas = []
    for entry in manifest.get("sessions", []):
        a_wall = entry.get("A", {}).get("wall_s")
        b_wall = entry.get("B", {}).get("wall_s")
        if a_wall and b_wall:
            wall_deltas.append(b_wall / a_wall - 1.0)
    result["wall_ratio_deltas"] = wall_deltas
    result["wall_median_delta"] = statistics.median(wall_deltas) if wall_deltas else None
    result["wall_mean_delta"] = statistics.fmean(wall_deltas) if wall_deltas else None

    # Session dispersion of the per-session p50 ratio.
    p50_deltas = []
    for meta in result["sessions"]:
        if meta["A_p50"] and meta["B_p50"]:
            p50_deltas.append(meta["B_p50"] / meta["A_p50"] - 1.0)
    result["p50_ratio_deltas"] = p50_deltas
    result["p50_median_delta"] = statistics.median(p50_deltas) if p50_deltas else None
    result["p50_mean_delta"] = statistics.fmean(p50_deltas) if p50_deltas else None
    result["p50_session_stdev"] = statistics.stdev(p50_deltas) if len(p50_deltas) > 1 else None

    # Null control: off vs off. A wide interval around zero is the noise floor.
    null_pairs = []
    for entry in manifest.get("null_control", []):
        a_steps, b_steps, _ = _session_values(entry, warmup)
        null_pairs.append((a_steps, b_steps))
    result["null_control_median"] = hierarchical_bootstrap(null_pairs, "median", replicates, random.Random(seed + 1))
    result["null_control_mean"] = hierarchical_bootstrap(null_pairs, "mean", replicates, random.Random(seed + 1))

    # A/A repeatability: the same arm twice.
    aa_pairs = []
    for entry in manifest.get("aa_repeat", []):
        a_steps, b_steps, _ = _session_values(entry, warmup)
        aa_pairs.append((a_steps, b_steps))
    result["aa_median"] = hierarchical_bootstrap(aa_pairs, "median", replicates, random.Random(seed + 2))
    result["aa_mean"] = hierarchical_bootstrap(aa_pairs, "mean", replicates, random.Random(seed + 2))

    # Decision rule (pre-registered): BOTH intervals' upper bounds < +0.5 %,
    # AND the whole-run wall time and steady-state p50 must jointly support it.
    median = result["median_ratio"]
    mean = result["mean_ratio"]
    wall_ok = result["wall_median_delta"] is not None and result["wall_median_delta"] < ACCEPTANCE_BOUND
    p50_ok = result["p50_median_delta"] is not None and result["p50_median_delta"] < ACCEPTANCE_BOUND
    bounded_ok = (
        median is not None and mean is not None and median["upper"] < ACCEPTANCE_BOUND and mean["upper"] < ACCEPTANCE_BOUND
    )
    if not (median and mean and wall_ok and p50_ok):
        verdict = "not yet demonstrated"
    elif bounded_ok and wall_ok and p50_ok:
        verdict = "overhead < 0.5%"
    else:
        verdict = "not yet demonstrated"
    result["wall_time_within_bound"] = wall_ok
    result["steady_state_p50_within_bound"] = p50_ok
    result["uncertainty_within_bound"] = bounded_ok
    result["verdict"] = verdict
    return result


def _selftest() -> int:
    """Prove the estimator runs and its interval behaves on synthetic data."""
    rng = random.Random(7)
    manifest: Dict[str, Any] = {
        "manifest_version": 1,
        "arms": {"A": "off", "B": "on"},
        "warmup_steps": 5,
        "bootstrap": {"replicates": 500, "seed": 1},
        "sessions": [],
    }
    # Six paired sessions; ON is +0.1 % slower with session-level offsets.
    for index in range(6):
        offset = rng.uniform(-0.01, 0.01)
        a = [1.0 + offset + rng.gauss(0, 0.01) for _ in range(60)]
        b = [value * 1.001 for value in a]
        manifest["sessions"].append(
            {
                "session": f"S{index}",
                "order": "A->B" if index % 2 == 0 else "B->A",
                "A": {"steps": a},
                "B": {"steps": b},
            }
        )
    result = analyse(manifest)
    assert result["median_ratio"] is not None
    assert result["median_ratio"]["lower"] <= result["median_ratio"]["point"] <= result["median_ratio"]["upper"]
    # ON is +0.1 % slower by construction; a sign inversion must fail here.
    assert result["median_ratio"]["point"] > 0.0, result["median_ratio"]
    assert result["mean_ratio"]["point"] > 0.0, result["mean_ratio"]
    assert result["verdict"] in ("overhead < 0.5%", "not yet demonstrated")
    print(json.dumps({k: result[k] for k in ("median_ratio", "mean_ratio", "verdict")}, indent=2))
    print("SELFTEST_OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path, default=None)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--freeze", action="store_true", help="print this file's sha256 for the manifest")
    args = parser.parse_args()

    if args.freeze:
        digest = hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()
        print(json.dumps({"estimator": str(pathlib.Path(__file__).resolve()), "sha256": digest}))
        return 0
    if args.selftest:
        return _selftest()
    if args.manifest is None:
        parser.error("manifest is required unless --selftest/--freeze is used")

    manifest = json.loads(args.manifest.read_text())
    # A manifest that declares a different estimator hash was produced against a
    # different estimator; refuse rather than silently mix.
    declared = manifest.get("estimator_sha256")
    actual = hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()
    if declared and declared != actual:
        print(f"estimator hash mismatch: manifest={declared} file={actual}", file=sys.stderr)
        return 2
    result = analyse(manifest)
    result["estimator_sha256"] = actual
    text = json.dumps(result, indent=2, sort_keys=True, default=str)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())