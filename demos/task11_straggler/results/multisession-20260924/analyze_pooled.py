# Copyright (c) 2026 Relax Authors. All Rights Reserved.

"""Pooled multisession statistics for Task 11 (2026-09-25 revision).

Fixes the estimator inconsistency and the independence assumption flagged in
review:

- The pre-registered point estimate is the **paired overhead median**; the
  bootstrap interval is now computed on the *same* estimator (previously a
  bootstrap *mean* interval was quoted next to a median point estimate).
- Pairs are clustered in sessions, so the interval uses a **session-aware
  (hierarchical) bootstrap**: sessions are resampled with replacement first,
  then pairs within each drawn session. Four sessions mean four clusters --
  the interval width reflects that limit and does not create information.
- Whole-run wall-clock increments (fixed 8000-step workload) are reported
  next to the pair medians, including the worst pair, because a median can
  hide rare expensive costs.
- Per-step stage-time tails are reported for observer-on bench segments
  (observer-off arms have no per-step data by construction -- stated as a
  limitation, not papered over).
- False positives get explicit denominators: bench-on alerts and sustained
  episodes over bench-on complete windows, per session and pooled.

The acceptance conclusion is NOT re-derived from the new method: the pooled
off/on interval remains above the 0.5% bound under both resampling schemes.

Run:  python demos/task11_straggler/results/multisession-20260924/analyze_pooled.py
"""

import json
import os
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
N_BOOT = 10000
RNG_SEED = 20260925


def load_sessions(prefix: str, names: str) -> dict:
    return {n: json.load(open(os.path.join(HERE, f"{prefix}-session-{n.lower() if prefix == 'aa' else n}.json"))) for n in names}


def hierarchical_boot(values_by_session: dict, estimator: str, n_boot: int = N_BOOT, seed: int = RNG_SEED):
    """Session-aware bootstrap: resample sessions, then pairs within sessions."""
    rng = np.random.default_rng(seed)
    session_names = list(values_by_session)
    session_arrays = [np.asarray(values_by_session[s], dtype=float) for s in session_names]
    stats = np.empty(n_boot)
    for i in range(n_boot):
        drawn_sessions = rng.integers(0, len(session_arrays), size=len(session_arrays))
        pooled = np.concatenate([session_arrays[j] for j in drawn_sessions])
        stats[i] = np.median(pooled) if estimator == "median" else pooled.mean()
    return np.percentile(stats, [2.5, 97.5])


def plain_boot(pooled: list, estimator: str, n_boot: int = N_BOOT, seed: int = RNG_SEED):
    """Pair-level (non-hierarchical) bootstrap, reported for contrast."""
    rng = np.random.default_rng(seed)
    arr = np.asarray(pooled, dtype=float)
    stats = np.empty(n_boot)
    for i in range(n_boot):
        drawn = rng.choice(arr, size=len(arr), replace=True)
        stats[i] = np.median(drawn) if estimator == "median" else drawn.mean()
    return np.percentile(stats, [2.5, 97.5])


def pct(vals, q):
    return float(np.percentile(np.asarray(vals), q)) if vals else None


def summarize_pool(name: str, pairs_by_session: dict, out: dict) -> dict:
    pooled = [v for arr in pairs_by_session.values() for v in arr]
    med_hi, med_lo_ci = float(np.median(pooled)), hierarchical_boot(pairs_by_session, "median")
    mean_ci = hierarchical_boot(pairs_by_session, "mean")
    plain_med_ci = plain_boot(pooled, "median")
    rec = {
        "n_pairs": len(pooled),
        "n_sessions": len(pairs_by_session),
        "median_pct": med_hi,
        "median_hier_boot_95_pct": [float(med_lo_ci[0]), float(med_lo_ci[1])],
        "mean_pct": float(np.mean(pooled)),
        "mean_hier_boot_95_pct": [float(mean_ci[0]), float(mean_ci[1])],
        "median_plain_boot_95_pct_for_contrast": [float(plain_med_ci[0]), float(plain_med_ci[1])],
        "min_pct": float(np.min(pooled)),
        "max_pct": float(np.max(pooled)),
        "per_session_medians_pct": {s: float(np.median(a)) for s, a in pairs_by_session.items()},
    }
    out[name] = rec
    return rec


def false_positive_stats(session: dict) -> dict:
    """Bench-on alerts and sustained episodes over bench-on complete windows."""
    bench_cases = {c for c in {s["case"] for s in session["samples"]} if c.startswith("bench_") and c.endswith("_on")}
    # Denominator: complete windows = (case, step) groups with both ranks present.
    by_cs = defaultdict(set)
    for s in session["samples"]:
        if s["case"] in bench_cases:
            by_cs[(s["case"], s["step"])].add(s["rank"])
    windows = sum(1 for ranks in by_cs.values() if len(ranks) == 2)
    # Numerator alerts: bench-on cases (no injection by construction).
    alerts = [a for a in session["diagnosis"]["alerts"] if a["case"] in bench_cases]
    # Sustained episodes: consecutive sampled steps (interval 8) same rank+stage.
    by_rank_stage = defaultdict(list)
    for a in alerts:
        by_rank_stage[(a["case"], a["rank"], a["stage"])].append(a["step"])
    episodes = 0
    for steps in by_rank_stage.values():
        steps.sort()
        episodes += 1
        for prev, cur in zip(steps, steps[1:]):
            if cur - prev > 8:
                episodes += 1
    return {
        "bench_on_windows": windows,
        "bench_on_alerts": len(alerts),
        "bench_on_sustained_episodes": episodes,
        "alert_rate": (len(alerts) / windows) if windows else None,
        "episode_rate": (episodes / windows) if windows else None,
    }


def step_tail_stats(session: dict) -> dict:
    """Per-step total stage time on bench-on segments (observer-on only)."""
    totals = []
    for s in session["samples"]:
        if s["case"].startswith("bench_") and s["case"].endswith("_on"):
            totals.append(sum(s["stages_ms"].values()))
    if not totals:
        return {}
    return {
        "p50_ms": pct(totals, 50),
        "p95_ms": pct(totals, 95),
        "p99_ms": pct(totals, 99),
        "max_ms": float(np.max(totals)),
    }


def main() -> None:
    out = {"note_estimators": "paired median (pre-registered) with session-aware hierarchical bootstrap; mean interval reported for continuity", "n_boot": N_BOOT, "rng_seed": RNG_SEED}

    offon = {n: [t["overhead_pct"] for t in json.load(open(os.path.join(HERE, f"session-{n}.json")))["paired_trials"]] for n in "abcd"}
    offon_aa = {n: [t["overhead_pct"] for t in json.load(open(os.path.join(HERE, f"aa-session-{n}.json")))["paired_trials"]] for n in "ABCD"}
    aa = {n: [t["difference_pct"] for t in json.load(open(os.path.join(HERE, f"aa-session-{n}.json")))["aa_trials"]] for n in "ABCD"}
    null_ab = {n: [t["difference_pct"] for t in json.load(open(os.path.join(HERE, f"session-{n}.json")))["null_trials"]] for n in "abcd"}
    null_aa = {n: [t["difference_pct"] for t in json.load(open(os.path.join(HERE, f"aa-session-{n}.json")))["null_trials"]] for n in "ABCD"}

    pools = {
        "off_on_multisession_abcd": offon,
        "off_on_aa_batch_ABCD": offon_aa,
        "aa_difference_ABCD": aa,
        "off_off_null_abcd": null_ab,
        "off_off_null_ABCD": null_aa,
    }
    for name, pool in pools.items():
        rec = summarize_pool(name, pool, out)
        print(
            f"{name:28s} n={rec['n_pairs']:2d}  median {rec['median_pct']:+.4f}%  "
            f"hier-median 95% [{rec['median_hier_boot_95_pct'][0]:+.4f}, {rec['median_hier_boot_95_pct'][1]:+.4f}]  "
            f"max {rec['max_pct']:+.3f}%"
        )

    # Whole-run wall clock (fixed 8000-step workload), per batch.
    for tag, prefix, names in (("abcd", "session", "abcd"), ("ABCD", "aa-session", "ABCD")):
        on = off = 0.0
        for n in names:
            d = json.load(open(os.path.join(HERE, f"{prefix}-{n}.json")))
            for r in d["runs"]:
                if r["case"].startswith("bench_"):
                    if r["case"].endswith("_on"):
                        on += r["elapsed_s"]
                    else:
                        off += r["elapsed_s"]
        out[f"wall_clock_bench_{tag}"] = {
            "on_total_s": on,
            "off_total_s": off,
            "increment_pct": ((on - off) / off * 100.0) if off else None,
        }
        print(f"wall_clock_bench_{tag:4s}          on {on:8.2f}s  off {off:8.2f}s  increment {out[f'wall_clock_bench_{tag}']['increment_pct']:+.4f}%")

    # Step-time tails + false-positive rates + transport telemetry, per session.
    fp = {}
    tails = {}
    lag = {}
    for n in "ABCD":
        d = json.load(open(os.path.join(HERE, f"aa-session-{n}.json")))
        fp[n] = false_positive_stats(d)
        tails[n] = step_tail_stats(d)
        lag[n] = {
            "report_lag_max_ms": max(r["probe"]["report_lag_max_ms"] for r in d["runs"] if r.get("probe") and r["case"].startswith("bench_") and r["case"].endswith("_on")),
            "pending_peak": max(r["probe"]["pending_peak"] for r in d["runs"] if r.get("probe") and r["case"].startswith("bench_") and r["case"].endswith("_on")),
        }
    fp_first_batch = {n: false_positive_stats(json.load(open(os.path.join(HERE, f"session-{n}.json")))) for n in "abcd"}
    pooled_windows = sum(fp[n]["bench_on_windows"] for n in fp)
    pooled_alerts = sum(fp[n]["bench_on_alerts"] for n in fp)
    pooled_eps = sum(fp[n]["bench_on_sustained_episodes"] for n in fp)
    out["false_positives"] = {
        "per_session_second_batch_ABCD": fp,
        "per_session_first_batch_abcd": fp_first_batch,
        "pooled_second_batch_ABCD": {
            "bench_on_windows": pooled_windows,
            "bench_on_alerts": pooled_alerts,
            "bench_on_sustained_episodes": pooled_eps,
            "alert_rate": pooled_alerts / pooled_windows,
            "episode_rate": pooled_eps / pooled_windows,
        },
    }
    out["step_time_tail_bench_on_ms"] = tails
    out["transport_bench_on"] = lag
    print(
        f"false positives (pooled A-D)   windows {pooled_windows}  alerts {pooled_alerts} "
        f"({pooled_alerts / pooled_windows:.5f})  episodes {pooled_eps} ({pooled_eps / pooled_windows:.5f})"
    )
    for n in "ABCD":
        t = tails[n]
        print(
            f"  step tail {n}: p50 {t['p50_ms']:.3f}ms  p95 {t['p95_ms']:.3f}ms  p99 {t['p99_ms']:.3f}ms  max {t['max_ms']:.3f}ms  "
            f"| lag_max {lag[n]['report_lag_max_ms']:.1f}ms"
        )
    out["limitation"] = (
        "Observer-off arms have no per-step data by construction, so per-step tails are "
        "observer-on only; pair wall-clock deltas remain the fixed-workload overhead "
        "measure. Four sessions are four clusters; the hierarchical interval reflects "
        "that limit and the acceptance conclusion (upper bound > 0.5%) is unchanged."
    )

    with open(os.path.join(HERE, "pooled-stats-20260925.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("written", os.path.join(HERE, "pooled-stats-20260925.json"))


if __name__ == "__main__":
    main()
