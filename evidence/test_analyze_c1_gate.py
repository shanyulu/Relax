#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Gate tests for analyze_c1.py: no defective input may reach PASS.

Every case below is a minimal counterexample. The PRE-FIX analyzer was
actually run on these exact cases and archived its wrongful verdicts in
``analyzer_gate_counterexamples/prefix_*.json`` — 9 of 10 defective cases were
wrongly adjudicated PASS (only the all-metric-missing case was caught). These
tests pin the POST-FIX behaviour: every defective case is excluded from the
eligible set and can never yield PASS.

Run:  python -m pytest test_analyze_c1_gate.py -q   (from this directory)
"""

import pathlib
import shutil
import sys

import pytest

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

import analyze_c1 as ac  # noqa: E402
import synth_campaign as sc  # noqa: E402

TMP = pathlib.Path("/tmp/opencode/synth_c1_gate")


def build(name, builder):
    root = TMP / name
    if root.exists():
        shutil.rmtree(root)
    builder(root)
    return root


def analyse(root, expected=None, min_pairs=6):
    return ac.analyse(root, ac.DEFAULT_METRIC, 500, 20260926, expected, min_pairs=min_pairs)


def one_pair(result):
    assert result["pairs"], "expected at least one pair entry"
    return result["pairs"][0]


# --- defective inputs: never eligible, never PASS ---------------------------------------

def test_understepped_arms_are_invalid_not_eligible():
    """Both arms complete only 2 of 48 steps."""
    root = build("understepped", lambda r: sc.write_pair(r, 1, n_steps=2, expected_steps=48))
    result = analyse(root)
    pair = one_pair(result)
    assert not pair["stats_eligible"]
    assert "under" in " ".join(
        [pair["off_classification"]["status"], pair["on_classification"]["status"]]
    ) or "step-ids" in pair["exclusion_reason"]
    assert result["verdict"]["c1_verdict"].startswith("INCONCLUSIVE")


def test_manifest_invalid_excludes_pair():
    root = build("manifest_invalid", lambda r: sc.write_pair(r, 1, off_valid=False, on_valid=False))
    pair = one_pair(analyse(root))
    assert not pair["stats_eligible"]
    assert "manifest.valid=false" in pair["exclusion_reason"]


def test_nonzero_exit_excludes_pair():
    root = build("nonzero_exit", lambda r: sc.write_pair(r, 1, on_exit_code=1))
    pair = one_pair(analyse(root))
    assert not pair["stats_eligible"]
    assert "nonzero-exit" in pair["on_classification"]["status"]


def test_duplicate_step_id_excludes_pair():
    root = build("duplicate_step", lambda r: sc.write_pair(r, 1, off_step_ids=list(range(47)) + [46]))
    pair = one_pair(analyse(root))
    assert not pair["stats_eligible"]
    assert "duplicate step IDs" in pair["exclusion_reason"]


def test_missing_step_id_excludes_pair():
    root = build("missing_step", lambda r: sc.write_pair(r, 1, on_step_ids=list(range(47))))
    pair = one_pair(analyse(root))
    assert not pair["stats_eligible"]
    assert "missing step IDs" in pair["exclusion_reason"]


def test_misaligned_step_id_excludes_pair():
    """Shifted IDs (1..48 for an expected 0..47) are both missing and extra;
    the missing-ID check fires first and the pair is excluded either way."""
    root = build("misaligned", lambda r: sc.write_pair(r, 1, on_step_ids=list(range(1, 49))))
    pair = one_pair(analyse(root))
    assert not pair["stats_eligible"]
    assert "missing step IDs" in pair["exclusion_reason"]


def test_metric_series_shorter_than_step_lines_excludes_pair():
    """Step lines exist for every ID but the analysis metric is absent."""
    root = build("metric_missing", lambda r: sc.write_pair(r, 1, off_metric_present=False))
    pair = one_pair(analyse(root))
    assert not pair["stats_eligible"]
    assert "no-training-steps" in pair["off_classification"]["status"] or "metric" in pair["exclusion_reason"]


def test_product_commit_mismatch_excludes_pair():
    root = build("commit_mismatch", lambda r: sc.write_pair(r, 1, on_commit=sc.COMMIT_ALT))
    pair = one_pair(analyse(root))
    assert not pair["stats_eligible"]
    assert "product commit differs" in pair["exclusion_reason"]


def test_dataset_mismatch_excludes_pair():
    root = build("dataset_mismatch", lambda r: sc.write_pair(r, 1, on_dataset=sc.DATASET_ALT))
    pair = one_pair(analyse(root))
    assert not pair["stats_eligible"]
    assert "dataset sha256 differs" in pair["exclusion_reason"]


def test_on_arm_without_profiler_enabled_excludes_pair():
    root = build("on_not_enabled", lambda r: sc.write_pair(r, 1, on_enable=None))
    pair = one_pair(analyse(root))
    assert not pair["stats_eligible"]
    assert "ON arm does not declare RELAX_STRAGGLER_ENABLE" in pair["exclusion_reason"]


def test_off_arm_with_profiler_enabled_excludes_pair():
    root = build("off_contaminated", lambda r: sc.write_pair(r, 1, off_enable="1"))
    pair = one_pair(analyse(root))
    assert not pair["stats_eligible"]
    assert "OFF arm declares RELAX_STRAGGLER_ENABLE" in pair["exclusion_reason"]


def test_on_arm_without_observation_evidence_excludes_pair():
    root = build("no_observation", lambda r: sc.write_pair(r, 1, on_collector_envelopes=0))
    pair = one_pair(analyse(root))
    assert not pair["stats_eligible"]
    assert "on-observation-missing" in pair["on_classification"]["status"]


def test_unregistered_step_count_makes_arms_invalid():
    """No manifest key and no CLI override: the observed count must NOT substitute."""
    root = build("no_expected", lambda r: sc.write_pair(r, 1, expected_steps=None))
    result = analyse(root)
    for arm in result["arms"]:
        assert arm["classification"]["status"] == "INVALID-unregistered-step-count"
    assert result["verdict"]["c1_verdict"].startswith("INCONCLUSIVE")
    # The same campaign with the preregistered count supplied via CLI is judged:
    result_cli = analyse(root, expected=48)
    assert one_pair(result_cli)["stats_eligible"]


def test_silent_truncation_is_rejected():
    """OFF has 48 steps, ON has 40: the pair must be excluded, not prefix-truncated."""
    root = build("truncation", lambda r: (sc.write_pair(r, 1, n_steps=48), None))
    # rewrite the ON arm with 40 steps and no manifest expected key mismatch:
    sc.write_arm(root / "S1-on" if False else root, "S1-on", n_steps=40, expected_steps=48,
                 values=[15.0 * 1.001] * 40, enable="1", started_at="2026-09-26T10:30:00")
    pair = one_pair(analyse(root))
    assert not pair["stats_eligible"]
    assert "not exactly aligned" in pair["exclusion_reason"]


# --- N=1 and small-n: no statistical PASS ----------------------------------------------

def test_single_pair_cannot_pass_even_with_low_overhead():
    """The pre-fix analyzer returned PASS here (degenerate bootstrap)."""
    root = build("single_pair", lambda r: sc.write_pair(r, 1, on_factor=1.001))
    result = analyse(root, min_pairs=6)
    assert one_pair(result)["stats_eligible"]  # the pair itself is valid...
    verdict = result["verdict"]
    assert verdict["c1_verdict"] == "INCONCLUSIVE-insufficient-pairs"  # ...but can never PASS
    assert verdict["primary_estimate_pct"] == pytest.approx(0.1, abs=1e-6)
    assert verdict["single_pair_caveat"] is True


def test_five_pairs_cannot_pass():
    root = build("five_pairs", lambda r: [sc.write_pair(r, i, on_factor=1.001) for i in range(1, 6)])
    result = analyse(root, min_pairs=6)
    assert result["session_stats"]["n_eligible_pairs"] == 5
    assert result["verdict"]["c1_verdict"] == "INCONCLUSIVE-insufficient-pairs"


def test_high_overhead_is_not_pass_at_any_n():
    root = build("high_overhead", lambda r: [sc.write_pair(r, i, on_factor=1.02) for i in range(1, 7)])
    result = analyse(root)
    assert result["verdict"]["c1_verdict"] == "NOT PASS"


# --- positive control: the analyzer CAN pass a well-formed campaign ---------------------

def test_six_well_formed_pairs_with_low_overhead_pass():
    root = build("six_good", lambda r: [sc.write_pair(r, i, on_factor=1.001) for i in range(1, 7)])
    result = analyse(root)
    assert result["session_stats"]["n_eligible_pairs"] == 6
    assert result["verdict"]["c1_verdict"] == "PASS"
    assert result["verdict"]["primary_estimate_pct"] == pytest.approx(0.1, abs=1e-6)
    assert result["verdict"]["bootstrap_ci_upper_pct"] < 0.5


def test_six_good_pairs_with_one_defective_arm_drop_to_five():
    """One corrupted arm removes its pair only; the verdict degrades honestly."""
    root = build("five_good_one_bad", lambda r: [sc.write_pair(r, i, on_factor=1.001) for i in range(1, 7)])
    sc.write_arm(root, "S3-on", n_steps=48, expected_steps=48, values=[15.015] * 48,
                 enable="1", started_at="2026-09-26T13:30:00", exit_code=1)
    result = analyse(root)
    assert result["session_stats"]["n_eligible_pairs"] == 5
    assert result["verdict"]["c1_verdict"] == "INCONCLUSIVE-insufficient-pairs"


# --- A/A control uses the same gates ----------------------------------------------------

def test_aa_noise_floor_rejects_invalid_off_arm():
    root = build("aa_invalid", lambda r: [sc.write_pair(r, 1), sc.write_pair(r, 2)])
    sc.write_arm(root, "S2-off", n_steps=48, expected_steps=48, values=[15.0] * 48,
                 started_at="2026-09-26T12:00:00", exit_code=3)
    result = analyse(root)
    noise = result["off_off_noise_floor"]
    assert noise["available"] is False
    assert "nonzero-exit" in noise["note"]


def test_aa_noise_floor_rejects_enabled_pseudo_on_arm():
    root = build("aa_contaminated", lambda r: [sc.write_pair(r, 1), sc.write_pair(r, 2)])
    sc.write_arm(root, "S2-off", n_steps=48, expected_steps=48, values=[15.0] * 48,
                 enable="1", started_at="2026-09-26T12:00:00")
    result = analyse(root)
    noise = result["off_off_noise_floor"]
    assert noise["available"] is False
    assert "profiler enabled" in noise["note"]


def test_aa_noise_floor_computes_for_two_valid_off_arms():
    root = build("aa_ok", lambda r: [sc.write_pair(r, 1), sc.write_pair(r, 2)])
    result = analyse(root)
    noise = result["off_off_noise_floor"]
    assert "deltas" in noise
    assert noise["deltas"]["whole_run_mean_delta_pct"] == pytest.approx(0.0, abs=1e-9)


# --- excluded-list consistency ------------------------------------------------------------

def test_excluded_list_matches_eligibility_set():
    """The verdict's 'invalid arms excluded' must be exactly the arms excluded."""
    root = build("excl_consistency", lambda r: [sc.write_pair(r, 1), sc.write_pair(r, 2, on_exit_code=1)])
    result = analyse(root)
    reason = result["verdict"]["c1_verdict_reason"]
    assert "invalid arms excluded: S2-on" in reason
    eligible_sessions = {p["session"] for p in result["pairs"] if p["stats_eligible"]}
    assert eligible_sessions == {"S1"}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
