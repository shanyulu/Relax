#!/usr/bin/env python3
"""Capture the PRE-FIX analyzer's behaviour on defective inputs (counterexamples)."""

import io
import json
import pathlib
import sys
import contextlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import synth_campaign as sc  # noqa: E402
import analyze_c1 as ac  # noqa: E402

ROOT = pathlib.Path("/tmp/opencode/synth_c1_prefix")
OUT = pathlib.Path("/tmp/opencode/evidence_wt/evidence/analyzer_gate_counterexamples")
OUT.mkdir(parents=True, exist_ok=True)


def run(name, builder, expected_steps=None):
    root = ROOT / name
    if root.exists():
        import shutil

        shutil.rmtree(root)
    builder(root)
    with contextlib.redirect_stdout(io.StringIO()):
        result = ac.analyse(root, ac.DEFAULT_METRIC, 2000, 20260926, expected_steps)
    pair = result["pairs"][0] if result["pairs"] else {}
    record = {
        "case": name,
        "expected_steps_resolved": result["expected_steps"],
        "expected_steps_source": result["expected_steps_source"],
        "arm_status": {a["name"]: a["classification"]["status"] for a in result["arms"]},
        "pair_eligible": pair.get("stats_eligible"),
        "exclusion_reason": pair.get("exclusion_reason"),
        "verdict": result["verdict"]["c1_verdict"],
        "primary_estimate_pct": result["verdict"]["primary_estimate_pct"],
    }
    print(json.dumps(record))
    (OUT / f"prefix_{name}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


# 1. single clean pair, +0.1% overhead, expected 48 (manifest) -> pre-fix verdict?
run("single_pair_low_overhead", lambda r: sc.write_pair(r, 1, on_factor=1.001, expected_steps=48))

# 2. both arms complete only 2 of 48 steps, no manifest expected -> max-observed fallback
run("two_of_48_steps_no_manifest", lambda r: sc.write_pair(r, 1, n_steps=2, expected_steps=None))

# 3. manifest.valid=false on both arms
run("manifest_invalid", lambda r: sc.write_pair(r, 1, off_valid=False, on_valid=False, expected_steps=48))

# 4. non-zero exit code on the ON arm
run("nonzero_exit_on", lambda r: sc.write_pair(r, 1, on_exit_code=1, expected_steps=48))

# 5. duplicate step id in the OFF arm
run("duplicate_step", lambda r: sc.write_pair(
    r, 1, off_step_ids=list(range(47)) + [46], expected_steps=48))

# 6. missing step id in the ON arm
run("missing_step", lambda r: sc.write_pair(
    r, 1, on_step_ids=list(range(47)), expected_steps=48))

# 7. ON arm built by a different product commit
run("commit_mismatch", lambda r: sc.write_pair(r, 1, on_commit=sc.COMMIT_ALT, expected_steps=48))

# 8. ON arm with the profiler not enabled
run("on_arm_not_enabled", lambda r: sc.write_pair(r, 1, on_enable=None, expected_steps=48))

# 9. ON arm with zero observed envelopes
run("on_arm_no_observation", lambda r: sc.write_pair(r, 1, on_collector_envelopes=0, expected_steps=48))

# 10. metric missing from every step line (OFF arm)
run("metric_missing_off", lambda r: sc.write_pair(r, 1, off_metric_present=False, expected_steps=48))
print("PRE-FIX CAPTURE DONE")
