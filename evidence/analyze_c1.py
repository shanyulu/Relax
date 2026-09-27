#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Criterion-1 (straggler-profiler overhead) analysis for a paired AB/BA GPU campaign.

Statistical unit is the PAIR / session, never the optimizer step. Per-step values are
only used to form one number per pair; the session-aware bootstrap resamples whole
pairs, never individual steps.

Usage:
    analyze_c1.py --campaign gpu_campaign/abba-cac4cb6-run4 [--out c1.json]
                  [--metric perf/train_time] [--expected-steps N]
                  [--bootstrap-replicates 10000] [--bootstrap-seed 20260926]

Every number printed here is parsed or computed from the campaign files; nothing is
hard-coded. If a log/summary is absent it is reported as absent, never substituted.

Definitions used (chosen to match the published first-pair numbers, and stated here so
the definition is never inferred from the answer):

    whole-run mean delta %   = (mean(ON) - mean(OFF)) / mean(OFF) * 100
    paired median delta %    = median over steps of (ON_i - OFF_i) / OFF_i * 100
    steady-state excl step 1 = the paired median definition over steps[1:]
    startup delta (s)        = ON[0] - OFF[0]
    median-of-deltas %       = (median(ON - OFF)) / median(OFF) * 100   (alternative)
    delta-of-medians %       = (median(ON) - median(OFF)) / median(OFF) * 100
"""

import argparse
import datetime as _dt
import json
import math
import pathlib
import random
import re
import statistics
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_METRIC = "perf/train_time"
DEFAULT_BOOTSTRAP_REPLICATES = 10000
DEFAULT_BOOTSTRAP_SEED = 20260926
C1_BOUND_PCT = 0.5  # official requirement: overall overhead < 0.5 %
#: PASS requires at least this many eligible pairs. The preregistered short
#: campaign is 6 AB/BA pairs; a single pair (N=1) has a degenerate bootstrap
#: interval (every resample is the same value) and can NEVER yield PASS.
DEFAULT_MIN_PAIRS = 6

ARM_DIR_RE = re.compile(r"^S(\d+)-(off|on)$")
# A per-step perf log line: "perf <int>: {'perf/x': 1.0, ...}".
PERF_STEP_RE = re.compile(r"\bperf\s+(\d+)\s*:\s*\{")
# "'<metric>': <number>" inside that dict; ints and floats, optional sign/exponent.
KV_NUM_RE = re.compile(r"'([^']+)'\s*:\s*(-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)")

# Manifest keys that may declare the pre-registered step count, in priority order.
EXPECTED_STEP_KEYS = ("expected_steps", "steps", "max_steps", "num_steps", "train_steps", "optimizer_steps")


# --------------------------------------------------------------------------------------
# parsing helpers
# --------------------------------------------------------------------------------------
def parse_started_at(value: Any) -> Optional[_dt.datetime]:
    """Parse a manifest 'started_at' timestamp; return None if unusable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = _dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_dt.timezone.utc)
        return parsed
    return None


def parse_metric_series(log_path: pathlib.Path) -> Dict[str, List[float]]:
    """Return {metric: [value, ...]} for every per-step perf dict in the log.

    Values are collected strictly in log order. A metric that is missing from some
    step lines simply has a shorter series; callers align the series they compare.
    """
    series: Dict[str, List[float]] = defaultdict(list)
    if not log_path.is_file():
        return {}
    with log_path.open("r", errors="replace") as handle:
        for line in handle:
            if not PERF_STEP_RE.search(line):
                continue
            for key, raw in KV_NUM_RE.findall(line):
                try:
                    value = float(raw)
                except ValueError:
                    continue
                if math.isnan(value) or math.isinf(value):
                    continue
                series[key].append(value)
    return dict(series)


def parse_step_labels(log_path: pathlib.Path) -> List[int]:
    """Return the 'perf <n>:' step labels in log order (for diagnostics)."""
    labels: List[int] = []
    if not log_path.is_file():
        return labels
    with log_path.open("r", errors="replace") as handle:
        for line in handle:
            match = PERF_STEP_RE.search(line)
            if match:
                labels.append(int(match.group(1)))
    return labels


def load_json(path: pathlib.Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None


# --------------------------------------------------------------------------------------
# statistics helpers
# --------------------------------------------------------------------------------------
def _percentile_nearest(ordered: List[float], fraction: float) -> float:
    """Nearest-rank percentile on a pre-sorted list (deterministic, no interpolation)."""
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def _safe_median(values: List[float]) -> Optional[float]:
    return statistics.median(values) if values else None


def _safe_mean(values: List[float]) -> Optional[float]:
    return statistics.fmean(values) if values else None


def bootstrap_pairs(
    per_pair_values: List[float],
    replicates: int,
    seed: int,
    statistic: str,
) -> Optional[Dict[str, Any]]:
    """Session-aware bootstrap: resample PAIRS (with replacement), never steps.

    ``per_pair_values`` holds exactly one summary number per session; each replicate
    draws len(per_pair_values) pairs with replacement and aggregates them with
    ``statistic`` ('mean' or 'median'). Returns point estimate + 2.5/97.5 percentiles.
    """
    if not per_pair_values:
        return None
    rng = random.Random(seed)
    point = statistics.fmean(per_pair_values) if statistic == "mean" else statistics.median(per_pair_values)
    draws: List[float] = []
    count = len(per_pair_values)
    for _ in range(replicates):
        sample = [per_pair_values[rng.randrange(count)] for _ in range(count)]
        draws.append(statistics.fmean(sample) if statistic == "mean" else statistics.median(sample))
    draws.sort()
    return {
        "statistic": statistic,
        "unit": "pair",
        "point": point,
        "lower": _percentile_nearest(draws, 0.025),
        "upper": _percentile_nearest(draws, 0.975),
        "n_pairs": count,
        "replicates": replicates,
        "seed": seed,
    }


def pair_delta_stats(off: List[float], on: List[float]) -> Dict[str, Any]:
    """Compute every per-pair delta statistic for one aligned OFF/ON series pair."""
    n = min(len(off), len(on))
    off_a, on_a = off[:n], on[:n]
    result: Dict[str, Any] = {
        "n_steps": n,
        "off_n": len(off),
        "on_n": len(on),
        "unaligned": len(off) != len(on),
    }
    if n == 0:
        result["computable"] = False
        return result

    deltas = [on_a[i] - off_a[i] for i in range(n)]
    relative = [(on_a[i] - off_a[i]) / off_a[i] for i in range(n) if off_a[i] != 0.0]
    mean_off = statistics.fmean(off_a)
    mean_on = statistics.fmean(on_a)
    median_off = statistics.median(off_a)
    median_on = statistics.median(on_a)

    result.update(
        {
            "computable": True,
            "off_mean_s": mean_off,
            "on_mean_s": mean_on,
            "off_median_s": median_off,
            "on_median_s": median_on,
            "whole_run_mean_delta_s": mean_on - mean_off,
            "whole_run_mean_delta_pct": 100.0 * (mean_on - mean_off) / mean_off if mean_off else None,
            "mean_delta_s": statistics.fmean(deltas),
            "paired_median_delta_s": statistics.median(deltas),
            "paired_median_delta_pct": 100.0 * statistics.median(relative) if relative else None,
            "median_of_deltas_pct_of_off_median": 100.0 * statistics.median(deltas) / median_off if median_off else None,
            "delta_of_medians_pct": 100.0 * (median_on - median_off) / median_off if median_off else None,
            "min_delta_s": min(deltas),
            "max_delta_s": max(deltas),
            "max_abs_delta_s": max(abs(value) for value in deltas),
            "min_rel_delta_pct": 100.0 * min(relative) if relative else None,
            "max_rel_delta_pct": 100.0 * max(relative) if relative else None,
            "startup_delta_s": deltas[0],
            "startup_off_s": off_a[0],
            "startup_on_s": on_a[0],
        }
    )

    if n >= 2:
        steady_deltas = deltas[1:]
        steady_rel = [(on_a[i] - off_a[i]) / off_a[i] for i in range(1, n) if off_a[i] != 0.0]
        steady_off = off_a[1:]
        steady_on = on_a[1:]
        result.update(
            {
                "steady_state_n": n - 1,
                "steady_state_median_delta_s": statistics.median(steady_deltas),
                "steady_state_median_delta_pct": 100.0 * statistics.median(steady_rel) if steady_rel else None,
                "steady_state_mean_delta_s": statistics.fmean(steady_deltas),
                "steady_state_mean_delta_pct": (
                    100.0 * (statistics.fmean(steady_on) - statistics.fmean(steady_off)) / statistics.fmean(steady_off)
                    if statistics.fmean(steady_off)
                    else None
                ),
                "steady_state_delta_of_medians_pct": (
                    100.0 * (statistics.median(steady_on) - statistics.median(steady_off)) / statistics.median(steady_off)
                    if statistics.median(steady_off)
                    else None
                ),
            }
        )
    else:
        result.update({"steady_state_n": 0})
    return result


# --------------------------------------------------------------------------------------
# campaign discovery
# --------------------------------------------------------------------------------------
def discover_arms(campaign: pathlib.Path) -> List[Dict[str, Any]]:
    """Find S<n>-off / S<n>-on arm directories and load their manifest + summary."""
    arms: List[Dict[str, Any]] = []
    for entry in sorted(campaign.iterdir()):
        if not entry.is_dir():
            continue
        match = ARM_DIR_RE.match(entry.name)
        if not match:
            continue
        session_index, arm = int(match.group(1)), match.group(2)
        manifest = load_json(entry / "manifest.json") or {}
        summary = load_json(entry / "summary.json") or {}
        log_path = entry / "job.log"
        series = parse_metric_series(log_path)
        arms.append(
            {
                "dir": str(entry),
                "name": entry.name,
                "session_index": session_index,
                "session": f"S{session_index}",
                "arm": arm,
                "manifest": manifest,
                "summary": summary,
                "job_log": str(log_path),
                "job_log_present": log_path.is_file(),
                "series": series,
                "step_labels": parse_step_labels(log_path),
                "started_at": manifest.get("started_at"),
                "started_at_parsed": parse_started_at(manifest.get("started_at")),
            }
        )
    return arms


def expected_step_count(arms: List[Dict[str, Any]], override: Optional[int]) -> Tuple[Optional[int], str]:
    """Resolve the PRE-REGISTERED step count. Resolution order is explicit.

    There is deliberately NO fallback to the observed sample count: treating
    the largest observed series as "expected" would bless a run that completed
    only 2 of 48 steps (demonstrated on the pre-fix analyzer, see
    analyzer_gate_counterexamples/prefix_two_of_48_steps_no_manifest.json).
    Without a preregistered count the campaign cannot prove step completeness
    and every arm is classified INVALID-unregistered-step-count.
    """
    if override is not None:
        return override, "cli --expected-steps"
    for arm in arms:
        manifest = arm["manifest"]
        for key in EXPECTED_STEP_KEYS:
            value = manifest.get(key)
            if isinstance(value, int) and value > 0:
                return value, f"manifest[{arm['name']}].{key}"
    return None, "unresolved (no preregistered step count in any manifest and no --expected-steps override)"


def classify_arm(arm: Dict[str, Any], expected_steps: Optional[int]) -> Dict[str, Any]:
    """VALID / INVALID classification with the full eligibility gate.

    An arm is VALID only when ALL of the following hold:
    - the manifest is not marked invalid (``manifest.valid is not False``);
    - the run exited successfully (``exit_code == 0``);
    - a PRE-REGISTERED step count is resolved (manifest key or CLI override —
      never the observed count);
    - the observed step-ID sequence is EXACTLY ``range(expected_steps)``:
      no duplicate, no missing, no extra/misaligned ID;
    - the analysis metric has exactly ``expected_steps`` samples (one per step,
      no step line missing the metric);
    - for an ON arm, the observation evidence exists: a collector status dict
      with at least one ingested envelope (a profiler that observed nothing
      cannot support an overhead claim about the enabled build).

    Pair eligibility requires BOTH arms VALID (never merely "n_steps > 0"),
    plus the pair fingerprint checks in :func:`pair_fingerprint`.
    """
    metric = DEFAULT_METRIC
    n_train = len(arm["series"].get(metric, []))
    manifest = arm["manifest"]
    summary = arm["summary"]
    observation = summary.get("observation") if isinstance(summary.get("observation"), dict) else {}
    collector_status = observation.get("collector_status")
    manifest_valid = manifest.get("valid")
    manifest_reason = manifest.get("invalid_reason")
    exit_code = manifest.get("exit_code")
    labels = arm["step_labels"]

    status = "VALID"
    reasons: List[str] = []

    if manifest_valid is False:
        status = "INVALID"
        reasons.append(f"manifest.valid=false ({manifest_reason or 'no reason recorded'})")
    elif not isinstance(exit_code, int) or exit_code != 0:
        status = "INVALID-nonzero-exit"
        reasons.append(f"exit_code={exit_code!r} (successful exit required)")
    elif expected_steps is None:
        status = "INVALID-unregistered-step-count"
        reasons.append("no preregistered step count; observed counts never substitute for one")
    else:
        expected_ids = list(range(expected_steps))
        duplicates = sorted({sid for sid in labels if labels.count(sid) > 1})
        missing = sorted(set(expected_ids) - set(labels))
        extra = sorted(set(labels) - set(expected_ids))
        if duplicates:
            status = "INVALID-step-ids"
            reasons.append(f"duplicate step IDs: {duplicates[:8]}")
        elif missing:
            status = "INVALID-step-ids"
            reasons.append(f"missing step IDs: {missing[:8]}")
        elif extra:
            status = "INVALID-step-ids"
            reasons.append(f"unexpected step IDs (misaligned): {extra[:8]}")
        elif n_train != expected_steps:
            status = "INVALID-incomplete-metric-series"
            reasons.append(f"{n_train} {metric} samples for {len(labels)} step lines, expected {expected_steps}")
        elif arm["arm"] == "on":
            envelopes = collector_status.get("envelopes") if isinstance(collector_status, dict) else None
            if not isinstance(collector_status, dict):
                status = "INVALID-on-observation-missing"
                reasons.append(f"ON arm observation.collector_status={collector_status!r} is not a dict")
            elif not isinstance(envelopes, int) or envelopes < 1:
                status = "INVALID-on-observation-missing"
                reasons.append(f"ON arm collector observed envelopes={envelopes!r}; >=1 required")

    return {
        "status": status,
        "valid": status == "VALID",
        "n_train_steps": n_train,
        "n_step_lines": len(labels),
        "expected_steps": expected_steps,
        "exit_code": exit_code,
        "collector_status_kind": type(collector_status).__name__ if collector_status is not None else "absent",
        "collector_status_is_dict": isinstance(collector_status, dict),
        "collector_envelopes": collector_status.get("envelopes") if isinstance(collector_status, dict) else None,
        "manifest_valid": manifest_valid,
        "manifest_invalid_reason": manifest_reason,
        "reasons": reasons,
    }


TRUTHY_ENABLE = {"1", "t", "true", "y", "yes", "on"}


def _enabled(manifest: Dict[str, Any]) -> bool:
    """Whether the arm's manifest declares the straggler profiler enabled."""
    relax_env = manifest.get("relax_env")
    value = relax_env.get("RELAX_STRAGGLER_ENABLE") if isinstance(relax_env, dict) else None
    return isinstance(value, str) and value.strip().lower() in TRUTHY_ENABLE


def pair_fingerprint(off_arm: Dict[str, Any], on_arm: Dict[str, Any]) -> Dict[str, Any]:
    """Pair-level identity checks: same product, data and recipe; profiler on
    exactly one arm. A pair that fails these is not a controlled experiment."""
    problems: List[str] = []
    off_git = (off_arm["manifest"].get("git") or {}).get("commit")
    on_git = (on_arm["manifest"].get("git") or {}).get("commit")
    if off_git != on_git:
        problems.append(f"product commit differs: off={off_git} on={on_git}")
    off_ds = off_arm["manifest"].get("dataset_sha256")
    on_ds = on_arm["manifest"].get("dataset_sha256")
    if off_ds != on_ds:
        problems.append(f"dataset sha256 differs: off={off_ds} on={on_ds}")
    if off_arm["manifest"].get("recipe") != on_arm["manifest"].get("recipe"):
        problems.append("recipe differs between arms")
    off_on = _enabled(off_arm["manifest"])
    on_on = _enabled(on_arm["manifest"])
    if not on_on:
        problems.append("ON arm does not declare RELAX_STRAGGLER_ENABLE")
    if off_on:
        problems.append("OFF arm declares RELAX_STRAGGLER_ENABLE (baseline contaminated)")
    return {
        "ok": not problems,
        "problems": problems,
        "off_enabled": off_on,
        "on_enabled": on_on,
        "commit": off_git,
        "dataset_sha256": off_ds,
    }


def collector_status_projection(arm: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The counter fields that must be conserved, straight out of summary.json."""
    summary = arm["summary"]
    observation = summary.get("observation") if isinstance(summary.get("observation"), dict) else {}
    status = observation.get("collector_status")
    if not isinstance(status, dict):
        return None
    keys = (
        "envelopes",
        "judged_packets",
        "late_packets",
        "duplicate_packets",
        "invalid_packets",
        "verdicts",
        "envelope_path",
        "verdict_path",
    )
    return {key: status.get(key) for key in keys}


def perf_metrics_table(arm: Dict[str, Any]) -> Dict[str, Any]:
    """p50/p95/p99/mean/median (+n/min/max) for every perf metric, from summary.json."""
    summary = arm["summary"]
    perf = summary.get("perf_metrics") if isinstance(summary.get("perf_metrics"), dict) else {}
    out: Dict[str, Any] = {}
    for metric, values in sorted(perf.items()):
        if not isinstance(values, dict):
            continue
        # summary.json carries no 'median' key today; p50 is the median quantile, so it
        # is reported as 'median' with provenance recorded rather than silently dropped.
        has_median_key = "median" in values
        out[metric] = {
            "n": values.get("n"),
            "mean": values.get("mean"),
            "p50": values.get("p50"),
            "p95": values.get("p95"),
            "p99": values.get("p99"),
            "min": values.get("min"),
            "max": values.get("max"),
            "median": values.get("median") if has_median_key else values.get("p50"),
            "median_source": "summary.perf_metrics[metric].median" if has_median_key else "summary.perf_metrics[metric].p50",
        }
    return out


# --------------------------------------------------------------------------------------
# main analysis
# --------------------------------------------------------------------------------------
def analyse(
    campaign: pathlib.Path,
    metric: str,
    replicates: int,
    seed: int,
    expected_override: Optional[int],
    min_pairs: int = DEFAULT_MIN_PAIRS,
) -> Dict[str, Any]:
    arms = discover_arms(campaign)
    expected_steps, expected_source = expected_step_count(arms, expected_override)

    by_session: Dict[int, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for arm in arms:
        by_session[arm["session_index"]][arm["arm"]] = arm

    arm_reports: List[Dict[str, Any]] = []
    classifications: Dict[str, Dict[str, Any]] = {}
    for arm in arms:
        classification = classify_arm(arm, expected_steps)
        classifications[arm["name"]] = classification
        arm_reports.append(
            {
                "name": arm["name"],
                "session": arm["session"],
                "arm": arm["arm"],
                "dir": arm["dir"],
                "started_at": arm["started_at"],
                "manifest_order": arm["manifest"].get("order"),
                "slot": arm["manifest"].get("slot"),
                "exit_code": arm["manifest"].get("exit_code"),
                "wall_seconds": arm["manifest"].get("wall_seconds"),
                "job_log_present": arm["job_log_present"],
                "git_commit": (arm["manifest"].get("git") or {}).get("commit"),
                "git_tree_label": (arm["manifest"].get("git") or {}).get("tree_label"),
                "straggler_enabled": _enabled(arm["manifest"]),
                "classification": classification,
                "training_metrics": sorted(arm["series"].keys()),
                "series_lengths": {key: len(value) for key, value in sorted(arm["series"].items())},
                "perf_metrics": perf_metrics_table(arm),
                "collector_status": collector_status_projection(arm),
            }
        )

    analysis_metric = metric if any(metric in arm["series"] for arm in arms) else DEFAULT_METRIC

    pairs: List[Dict[str, Any]] = []
    unpaired: List[Dict[str, Any]] = []
    for session_index in sorted(by_session):
        group = by_session[session_index]
        off_arm, on_arm = group.get("off"), group.get("on")
        session_name = f"S{session_index}"
        if off_arm is None or on_arm is None:
            missing = "off" if off_arm is None else "on"
            present = on_arm if off_arm is None else off_arm
            unpaired.append(
                {
                    "session": session_name,
                    "missing_arm": missing,
                    "present_arm": present["name"] if present else None,
                    "reason": f"no S{session_index}-{missing} directory; session is not a complete pair",
                }
            )
            continue

        order = "unknown"
        first = "unknown"
        if off_arm["started_at_parsed"] and on_arm["started_at_parsed"]:
            if off_arm["started_at_parsed"] <= on_arm["started_at_parsed"]:
                first, order = "off", "off->on (AB)"
            else:
                first, order = "on", "on->off (BA)"

        off_cls = classifications[off_arm["name"]]
        on_cls = classifications[on_arm["name"]]
        fingerprint = pair_fingerprint(off_arm, on_arm)
        off_series = off_arm["series"].get(analysis_metric, [])
        on_series = on_arm["series"].get(analysis_metric, [])
        stats = pair_delta_stats(off_series, on_series)
        exact_alignment = stats.get("off_n") == stats.get("on_n") and not stats.get("unaligned")

        # Eligibility = BOTH arms fully VALID + the pair is a controlled
        # experiment (same product/data/recipe, profiler on exactly the ON arm)
        # + exact step alignment. "n_steps > 0" alone was NEVER a valid gate:
        # the pre-fix analyzer passed manifest-invalid, non-zero-exit,
        # duplicate-step and commit-mismatch pairs (counterexamples archived).
        problems: List[str] = []
        if not off_cls["valid"]:
            problems.append(f"off arm {off_cls['status']}: {'; '.join(off_cls['reasons'])}")
        if not on_cls["valid"]:
            problems.append(f"on arm {on_cls['status']}: {'; '.join(on_cls['reasons'])}")
        problems.extend(fingerprint["problems"])
        if not exact_alignment:
            problems.append(
                f"step series not exactly aligned (off {stats.get('off_n')} vs on {stats.get('on_n')} samples); "
                "silent truncation to the shorter arm is not permitted"
            )
        pair_ok = not problems

        pairs.append(
            {
                "session": session_name,
                "order": order,
                "first_arm": first,
                "manifest_order_off": off_arm["manifest"].get("order"),
                "manifest_order_on": on_arm["manifest"].get("order"),
                "metric": analysis_metric,
                "off_dir": off_arm["name"],
                "on_dir": on_arm["name"],
                "off_classification": off_cls,
                "on_classification": on_cls,
                "fingerprint": fingerprint,
                "exact_alignment": exact_alignment,
                "stats_eligible": pair_ok,
                "exclusion_reason": None if pair_ok else " | ".join(problems),
                "deltas": stats,
            }
        )

    eligible = [pair for pair in pairs if pair["stats_eligible"]]
    whole_run_pct = [pair["deltas"]["whole_run_mean_delta_pct"] for pair in eligible]
    whole_run_pct = [value for value in whole_run_pct if value is not None]
    paired_median_pct = [pair["deltas"]["paired_median_delta_pct"] for pair in eligible]
    paired_median_pct = [value for value in paired_median_pct if value is not None]
    steady_pct = [
        pair["deltas"].get("steady_state_median_delta_pct")
        for pair in eligible
        if pair["deltas"].get("steady_state_median_delta_pct") is not None
    ]

    session_stats = {
        "n_eligible_pairs": len(eligible),
        "whole_run_mean_pct_across_pairs_mean": _safe_mean(whole_run_pct),
        "whole_run_mean_pct_across_pairs_median": _safe_median(whole_run_pct),
        "paired_median_pct_across_pairs_mean": _safe_mean(paired_median_pct),
        "paired_median_pct_across_pairs_median": _safe_median(paired_median_pct),
        "steady_state_median_pct_across_pairs_mean": _safe_mean(steady_pct),
        "steady_state_median_pct_across_pairs_median": _safe_median(steady_pct),
        "bootstrap_seed": seed,
        "bootstrap_replicates": replicates,
        "bootstrap_whole_run_mean_pct": bootstrap_pairs(whole_run_pct, replicates, seed, "mean"),
        "bootstrap_paired_median_pct": bootstrap_pairs(paired_median_pct, replicates, seed, "median"),
    }

    # OFF/OFF noise floor: the A/A control passes through the SAME validity and
    # fingerprint gates as an OFF/ON pair — an invalid OFF arm cannot support a
    # noise-floor claim any more than an invalid ON arm can support overhead.
    off_arms = [arm for arm in arms if arm["arm"] == "off"]
    noise_floor = None
    if len(off_arms) < 2:
        noise_floor = {
            "metric": analysis_metric,
            "available": False,
            "note": f"only {len(off_arms)} OFF arm(s) in this campaign; OFF/OFF noise floor not computable",
        }
    else:
        first_off, second_off = off_arms[0], off_arms[1]
        cls_a = classifications[first_off["name"]]
        cls_b = classifications[second_off["name"]]
        aa_problems: List[str] = []
        if not cls_a["valid"]:
            aa_problems.append(f"{first_off['name']} {cls_a['status']}: {'; '.join(cls_a['reasons'])}")
        if not cls_b["valid"]:
            aa_problems.append(f"{second_off['name']} {cls_b['status']}: {'; '.join(cls_b['reasons'])}")
        # A/A identity: same product/data/recipe as an OFF/ON pair, but the
        # enable asymmetry is inverted — the pseudo-ON arm must NOT have the
        # profiler on (a contaminated A/A cannot measure noise).
        for field, label in (("git", "commit"), ("dataset_sha256", "dataset sha256"), ("recipe", "recipe")):
            if first_off["manifest"].get(field) != second_off["manifest"].get(field):
                if field == "git":
                    aa_problems.append(
                        "product commit differs: "
                        f"{(first_off['manifest'].get('git') or {}).get('commit')} vs "
                        f"{(second_off['manifest'].get('git') or {}).get('commit')}"
                    )
                else:
                    aa_problems.append(f"{label} differs between the A/A arms")
        if _enabled(second_off["manifest"]):
            aa_problems.append("pseudo-ON arm of the A/A control has the profiler enabled")
        if aa_problems:
            noise_floor = {
                "metric": analysis_metric,
                "available": False,
                "note": "A/A control failed the same validity/fingerprint gates: " + " | ".join(aa_problems),
            }
        else:
            noise_floor = {
                "metric": analysis_metric,
                "arm_a": first_off["name"],
                "arm_b": second_off["name"],
                "note": "second OFF arm treated as the pseudo-ON arm; both arms passed the full validity and fingerprint gates",
                "deltas": pair_delta_stats(
                    first_off["series"].get(analysis_metric, []), second_off["series"].get(analysis_metric, [])
                ),
            }

    verdict = build_verdict(session_stats, eligible, arms, pairs, unpaired, classifications, min_pairs)

    return {
        "tool": "analyze_c1.py",
        "campaign": str(campaign),
        "analysis_metric": analysis_metric,
        "requested_metric": metric,
        "expected_steps": expected_steps,
        "expected_steps_source": expected_source,
        "min_pairs_for_pass": min_pairs,
        "c1_bound_pct": C1_BOUND_PCT,
        "arms": arm_reports,
        "pairs": pairs,
        "unpaired": unpaired,
        "session_stats": session_stats,
        "off_off_noise_floor": noise_floor,
        "verdict": verdict,
    }


def build_verdict(
    session_stats: Dict[str, Any],
    eligible: List[Dict[str, Any]],
    arms: List[Dict[str, Any]],
    pairs: List[Dict[str, Any]],
    unpaired: List[Dict[str, Any]],
    classifications: Dict[str, Dict[str, Any]],
    min_pairs: int,
) -> Dict[str, Any]:
    """Apply the strict C1 rule.

    PASS requires ALL of:
    - at least ``min_pairs`` eligible pairs (the preregistered campaign size;
      N=1 has a degenerate bootstrap interval and can never PASS);
    - the whole-run session-level estimate < 0.5 %;
    - the session-aware bootstrap 95% CI upper bound < 0.5 %.

    A median < 0.5 % alone, or a steady-state < 0.5 % alone, is explicitly
    never PASS. The excluded-arms list is built from the SAME classification
    objects that decided eligibility (the pre-fix code re-classified with
    ``expected_steps=None``, so the reported exclusions could differ from the
    set actually applied).
    """
    invalid_arms = [name for name, cls in classifications.items() if not cls["valid"]]
    estimate = session_stats["whole_run_mean_pct_across_pairs_mean"]
    bootstrap = session_stats["bootstrap_whole_run_mean_pct"]
    median_est = session_stats["paired_median_pct_across_pairs_mean"]
    steady_est = session_stats["steady_state_median_pct_across_pairs_mean"]
    n_pairs = session_stats["n_eligible_pairs"]
    seed = session_stats["bootstrap_seed"]
    upper = bootstrap["upper"] if bootstrap else None

    tail = (
        "a median or steady-state estimate below 0.5 % alone must NOT yield PASS "
        f"(paired median across pairs {_fmt_pct(median_est)}, steady-state median across pairs {_fmt_pct(steady_est)})."
    )
    excluded = []
    if invalid_arms:
        excluded.append("invalid arms excluded: " + ", ".join(invalid_arms))
    if unpaired:
        excluded.append("unpaired sessions: " + ", ".join(item["session"] for item in unpaired))
    extra = (" " + "; ".join(excluded) + ".") if excluded else ""

    if estimate is None or n_pairs == 0:
        verdict = "INCONCLUSIVE"
        reason = (
            f"C1 INCONCLUSIVE: no eligible OFF/ON pair in this campaign "
            f"({n_pairs} eligible pairs); " + tail + extra
        )
    elif n_pairs < min_pairs:
        verdict = "INCONCLUSIVE-insufficient-pairs"
        reason = (
            f"C1 INCONCLUSIVE: only {n_pairs} eligible pair(s) < {min_pairs} required for a statistical verdict; "
            f"the whole-run point estimate {_fmt_pct(estimate)} is reported as a conditional point estimate only. "
            f"With n_pairs={n_pairs} the bootstrap interval is degenerate (every resample draws the same value), "
            f"so no population-level claim is made. " + tail + extra
        )
    elif estimate < C1_BOUND_PCT and upper is not None and upper < C1_BOUND_PCT:
        verdict = "PASS"
        reason = (
            f"C1 PASS: session-level whole-run mean overhead {_fmt_pct(estimate)} (n_pairs={n_pairs} >= {min_pairs}) "
            f"is < {C1_BOUND_PCT}% and its session-aware bootstrap 95% CI upper bound {_fmt_pct(upper)} "
            f"(seed {seed}, {session_stats['bootstrap_replicates']} replicates, pair-resampled) is < {C1_BOUND_PCT}%."
            + extra
        )
    elif estimate < C1_BOUND_PCT:
        verdict = "INCONCLUSIVE-wide-interval"
        reason = (
            f"C1 INCONCLUSIVE: session-level whole-run mean overhead {_fmt_pct(estimate)} (n_pairs={n_pairs}) is "
            f"< {C1_BOUND_PCT}% but the session-aware bootstrap 95% CI upper bound {_fmt_pct(upper)} "
            f"(seed {seed}, pair-resampled) is not < {C1_BOUND_PCT}%; " + tail + extra
        )
    else:
        verdict = "NOT PASS"
        reason = (
            f"C1 NOT PASS: session-level whole-run mean overhead {_fmt_pct(estimate)} (n_pairs={n_pairs}) "
            f"is not < {C1_BOUND_PCT}%; " + tail + extra
        )

    return {
        "c1_verdict": verdict,
        "c1_verdict_reason": reason,
        "primary_estimate_pct": estimate,
        "primary_estimate_kind": "mean across pairs of per-pair whole-run mean delta %",
        "bootstrap_ci_upper_pct": upper,
        "median_estimate_pct": median_est,
        "steady_state_estimate_pct": steady_est,
        "median_alone_can_pass": False,
        "steady_state_alone_can_pass": False,
        "single_pair_caveat": bool(n_pairs < min_pairs),
        "min_pairs_for_pass": min_pairs,
        "bound_pct": C1_BOUND_PCT,
    }


def _fmt_pct(value: Optional[float]) -> str:
    return "null" if value is None else f"{value:+.3f}%"


def _fmt(value: Any, digits: int = 6) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return f"{value:.{digits}f}"
    return str(value)


def render_markdown(result: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"# Criterion 1 analysis — `{result['campaign']}`")
    lines.append("")
    lines.append(
        f"- metric: `{result['analysis_metric']}` (requested `{result['requested_metric']}`)"
    )
    lines.append(
        f"- expected step count: {_fmt(result['expected_steps'])} (source: {result['expected_steps_source']})"
    )
    lines.append(f"- acceptance bound: whole-run overhead < {result['c1_bound_pct']}%")
    stats = result["session_stats"]
    lines.append(
        f"- bootstrap: seed {stats['bootstrap_seed']}, {stats['bootstrap_replicates']} replicates, "
        "resampling PAIRS (not steps)"
    )
    lines.append("")

    lines.append("## Arm validity")
    lines.append("")
    lines.append("| arm | session | role | steps | expected | collector_status | git | status | reasons |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for arm in result["arms"]:
        cls = arm["classification"]
        commit = (arm.get("git_commit") or "")[:7]
        lines.append(
            "| {name} | {session} | {role} | {steps} | {expected} | {cs} | {commit} | {status} | {reasons} |".format(
                name=arm["name"],
                session=arm["session"],
                role=arm["arm"],
                steps=cls["n_train_steps"],
                expected=_fmt(cls["expected_steps"]),
                cs=cls["collector_status_kind"],
                commit=commit or "-",
                status=cls["status"],
                reasons="; ".join(cls["reasons"]) or "",
            )
        )
    lines.append("")

    lines.append("## Pair ordering and per-pair deltas")
    lines.append("")
    lines.append(
        "| session | order (manifest start ts) | metric n | whole-run mean Δ% | whole-run mean Δs | paired median Δ% | "
        "median-of-Δs % | Δ-of-medians % | steady median Δ% (excl 1) | steady mean Δ% | startup Δs | min Δs | max Δs | max\\|Δ\\| s | eligible |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for pair in result["pairs"]:
        d = pair["deltas"]
        lines.append(
            "| {s} | {o} | {n} | {wrp} | {wra} | {pm} | {md} | {dm} | {sm} | {smean} | {su} | {mn} | {mx} | {mxa} | {elig} |".format(
                s=pair["session"],
                o=pair["order"],
                n=d.get("n_steps", 0),
                wrp=_fmt(d.get("whole_run_mean_delta_pct"), 4),
                wra=_fmt(d.get("whole_run_mean_delta_s"), 6),
                pm=_fmt(d.get("paired_median_delta_pct"), 4),
                md=_fmt(d.get("median_of_deltas_pct_of_off_median"), 4),
                dm=_fmt(d.get("delta_of_medians_pct"), 4),
                sm=_fmt(d.get("steady_state_median_delta_pct"), 4),
                smean=_fmt(d.get("steady_state_mean_delta_pct"), 4),
                su=_fmt(d.get("startup_delta_s"), 6),
                mn=_fmt(d.get("min_delta_s"), 6),
                mx=_fmt(d.get("max_delta_s"), 6),
                mxa=_fmt(d.get("max_abs_delta_s"), 6),
                elig="yes" if pair["stats_eligible"] else "no",
            )
        )
    if not result["pairs"]:
        lines.append("| (no complete pairs) | - | - | - | - | - | - | - | - | - | - | - | - | - | - |")
    lines.append("")

    if result["unpaired"]:
        lines.append("## Unpaired arms")
        lines.append("")
        for item in result["unpaired"]:
            lines.append(f"- {item['session']}: missing `{item['missing_arm']}` arm ({item['reason']})")
        lines.append("")

    lines.append("## Session-level statistics (unit = pair)")
    lines.append("")
    lines.append(f"- eligible pairs: {stats['n_eligible_pairs']}")
    lines.append(
        f"- whole-run mean Δ%: mean across pairs {_fmt(stats['whole_run_mean_pct_across_pairs_mean'], 4)}, "
        f"median across pairs {_fmt(stats['whole_run_mean_pct_across_pairs_median'], 4)}"
    )
    lines.append(
        f"- paired median Δ%: mean across pairs {_fmt(stats['paired_median_pct_across_pairs_mean'], 4)}, "
        f"median across pairs {_fmt(stats['paired_median_pct_across_pairs_median'], 4)}"
    )
    lines.append(
        f"- steady-state median Δ%: mean across pairs {_fmt(stats['steady_state_median_pct_across_pairs_mean'], 4)}, "
        f"median across pairs {_fmt(stats['steady_state_median_pct_across_pairs_median'], 4)}"
    )
    for key, label in (
        ("bootstrap_whole_run_mean_pct", "whole-run mean Δ% (primary)"),
        ("bootstrap_paired_median_pct", "paired median Δ% (secondary)"),
    ):
        boot = stats.get(key)
        if boot:
            lines.append(
                f"- bootstrap 95% CI [{label}]: point {_fmt(boot['point'], 4)}%, "
                f"lower {_fmt(boot['lower'], 4)}%, upper {_fmt(boot['upper'], 4)}% "
                f"({boot['statistic']}, {boot['n_pairs']} pairs, seed {boot['seed']})"
            )
    lines.append("")

    noise = result["off_off_noise_floor"]
    lines.append("## OFF/OFF noise floor")
    lines.append("")
    if noise.get("available", True) and "deltas" in noise:
        d = noise["deltas"]
        lines.append(
            f"- {noise['arm_a']} vs {noise['arm_b']}: whole-run mean Δ {_fmt(d.get('whole_run_mean_delta_pct'), 4)}%, "
            f"paired median Δ {_fmt(d.get('paired_median_delta_pct'), 4)}%, max\\|Δ\\| {_fmt(d.get('max_abs_delta_s'))} s"
        )
    else:
        lines.append(f"- not computable: {noise['note']}")
    lines.append("")

    lines.append("## summary.json perf_metrics (both arms)")
    lines.append("")
    lines.append("| arm | metric | n | mean | median (source) | p50 | p95 | p99 | min | max |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for arm in result["arms"]:
        for metric, values in arm["perf_metrics"].items():
            lines.append(
                "| {arm} | `{metric}` | {n} | {mean} | {med} ({src}) | {p50} | {p95} | {p99} | {mn} | {mx} |".format(
                    arm=arm["name"],
                    metric=metric,
                    n=_fmt(values.get("n")),
                    mean=_fmt(values.get("mean")),
                    med=_fmt(values.get("median")),
                    src=values.get("median_source", "-"),
                    p50=_fmt(values.get("p50")),
                    p95=_fmt(values.get("p95")),
                    p99=_fmt(values.get("p99")),
                    mn=_fmt(values.get("min")),
                    mx=_fmt(values.get("max")),
                )
            )
    lines.append("")

    verdict = result["verdict"]
    lines.append("## C1 verdict")
    lines.append("")
    lines.append(f"**{verdict['c1_verdict']}**")
    lines.append("")
    lines.append(verdict["c1_verdict_reason"])
    lines.append("")
    lines.append(
        "- rule: PASS requires the session-level whole-run estimate < 0.5 %; "
        "`median < 0.5 %` alone and `steady-state < 0.5 %` alone never yield PASS."
    )
    lines.append("")
    lines.append("## Definitions (stated so they are never inferred from the answer)")
    lines.append("")
    lines.append("- `whole-run mean Δ%` = `(mean(ON) - mean(OFF)) / mean(OFF) * 100` over the pair's aligned steps.")
    lines.append(
        "- `paired median Δ%` = median over steps of `(ON_i - OFF_i) / OFF_i * 100` "
        "(the definition that reproduces the published first-pair `+0.195 %`)."
    )
    lines.append("- `steady median Δ% (excl 1)` = the same paired-median definition over `steps[1:]` (step 1 excluded).")
    lines.append("- `startup Δs` = `ON[0] - OFF[0]`.")
    lines.append("- `median-of-Δs %` = `median(ON - OFF) / median(OFF) * 100`; `Δ-of-medians %` = `(median(ON) - median(OFF)) / median(OFF) * 100` (alternatives, reported for transparency).")
    lines.append("- `median` in the `perf_metrics` table is read from `summary.json` `perf_metrics[metric].median` when present, otherwise from its `p50` (the source column records which).")
    lines.append("- Bootstrap resamples whole PAIRS with replacement; per-step values are never treated as independent.")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--campaign", required=True, type=pathlib.Path, help="campaign directory of S<n>-off/S<n>-on arms")
    parser.add_argument("--out", type=pathlib.Path, default=None, help="write the JSON summary here")
    parser.add_argument("--metric", default=DEFAULT_METRIC, help=f"primary metric (default {DEFAULT_METRIC})")
    parser.add_argument("--expected-steps", type=int, default=None, help="override the expected perf/train_time sample count")
    parser.add_argument("--bootstrap-replicates", type=int, default=DEFAULT_BOOTSTRAP_REPLICATES)
    parser.add_argument("--bootstrap-seed", type=int, default=DEFAULT_BOOTSTRAP_SEED)
    parser.add_argument(
        "--min-pairs",
        type=int,
        default=DEFAULT_MIN_PAIRS,
        help=f"minimum eligible pairs for a PASS verdict (default {DEFAULT_MIN_PAIRS}); "
        "fewer pairs can only yield INCONCLUSIVE with a conditional point estimate",
    )
    args = parser.parse_args(argv)

    campaign = args.campaign
    if not campaign.is_dir():
        parser.error(f"campaign directory not found: {campaign}")

    result = analyse(
        campaign,
        args.metric,
        args.bootstrap_replicates,
        args.bootstrap_seed,
        args.expected_steps,
        min_pairs=args.min_pairs,
    )
    markdown = render_markdown(result)

    print(markdown)
    payload = json.dumps(result, indent=2, sort_keys=True, default=str)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n")
        print(f"[json] wrote {args.out}")
    else:
        print("<!-- JSON -->")
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())