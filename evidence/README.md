# Task 11 Straggler Profiler — Immutable Evidence

Branch: `evidence/task11-straggler` (append-only; never force-pushed).

Producing product SHA: `cac4cb6447154e6ae4f563eabab7fecf43dba790`
(product freeze; PR heads above it are test/docs-only).

Contents:
- `TASK11_FINAL_ACCEPTANCE_PROTOCOL.md` / `TASK11_C2C3_PROTOCOL.md` — preregistered
  acceptance protocols (frozen estimators, tolerances, seeds).
- `TASK11_C1_LONGRUN_PROTOCOL.md` — preregistered long-run confirmatory protocol
  (480 steps, whole-run accounting, committed before any long-run data).
- `TASK11_STARTUP_DECOMPOSITION.md` + `tools/straggler_startup_decompose.py` —
  preregistered plan and script locating the one-off +15.699 s start-up delta.
- `TASK11_FINAL_ACCEPTANCE_REPORT.md` — the acceptance report (20 sections +
  closeout addenda), including the environment-incident appendix.
- `TASK11_ENV_FINGERPRINT.json` — machine/stack fingerprint (re-captured at
  every campaign start per protocol).
- `gpu_campaign/` — every arm ever run, valid and invalid (never deleted):
  includes the unique valid pair `abba-cac4cb6-run4` (S1-off/S1-on),
  historical comparison arms, and the environment-failure arms.
- `env_incident_20260926_evening/` — the machine-level CUDA-in-Ray incident:
  reproducer, 13-case elimination matrix, canary artifacts, re-entry tests
  (including the 2026-09-27 morning re-entry attempts, `reentry_20260927_*`).
- `environment/pre_repair/` — pre-repair environment snapshot.
- `docs_staged/` — the bilingual user-guide sources as committed to the PR.
- Analysis scripts (`analyze_c1.py` frozen estimator, `analyze_run.py`,
  `audit_counters_v2.py`, `report_latency.py`) and their machine-recomputed
  outputs (counter conservation, latency percentiles).

Every acceptance number cited in RFC #357 / PR #378 is reproducible from a file
in this tree at the producing commit recorded with it.

## Current-build closeout addenda (build `a48a23b`, 2026-09-27)

- `D1_D2_CORRECTNESS_GATE.md` — the two detector state-machine holes (below-floor
  UNCERTAIN+RECOVERED; pre-onset streak across unusable windows) closed with
  old-fail (`e961661`: 6 failed) / new-pass (`a48a23b`: 411 passed, 2 skipped)
  evidence and the exact pinned tests.
- `C1_CONFIRMATORY_PROTOCOL_A48A23B.md` — the `e961661` 6-pair campaign frozen as
  PILOT; exact pair-level statistics; metric-option A/B feasibility table
  (train_time ≈2,292–3,253 pairs vs wall-clock ≈14–20 pairs); fixed-N one-shot
  confirmatory design; LONGRUN_STEPS=531 (natural epoch); S1/S2-off renamed
  cross-session OFF/OFF diagnostic contrast.
- `tools/campaign_lock.py` — CAMPAIGN_LOCK generator/validator: exact-SHA clean-tree
  product pin, recipe/dataset/env hashes, ON-arm env profile enforcement,
  lock_sha256 referenced by every arm manifest.
- `TRACE_PROTOCOL_A48A23B.md` — trace backend declared BEFORE any trace (Nsight
  install attempts recorded and blocked; torch.profiler/Kineto primary);
  programmatic metrics (overlap_ratio, new_global_sync, …); screenshot evidence
  forbidden.
- `C2_PROTOCOL_A48A23B.md` — freeze-before-see order (OFF/OFF calibration pairs →
  ON/OFF pairs), SAVE=1 checkpoint equivalence (exact hashes if deterministic,
  10×-calibration-99th-percentile tolerances if not), ≥2+2 pairs minimum.
- `C3_HARNESS_DESIGN_A48A23B.md` — external non-invasive harness (schema has no
  timestamps; no product change for C3 this phase); E2E latency without queueing
  subtraction; real-verdict/tail-window/silent-tail/platform-record evidence set.
- Superseded-for-current-build history retained: the `cac4cb6` long-run and C2/C3
  protocols remain in place unchanged.

### Hardening addendum (same day, pre-GPU)

- `tools/campaign_lock.py` validate() rewritten for FULL enforcement (the earlier
  draft had a self-comparing recipe check that could never detect drift) —
  16 corruption classes now INVALID, plus a golden-manifest must-validate test
  (17 tests; old validator: 11 of 16 corruptions wrongly VALID).
- `tools/c2_lock.py` — two-stage C2 locking (calibration-lock → frozen
  calibration-result → measurement-lock referencing the result's sha →
  compare), tolerance priority EXACT_EQUALITY / established-precision /
  OFF_OFF_ENVELOPE_x2 (2× worst pairwise delta over 6 arms = 720 samples,
  envelope semantics declared; the "p99×10 from 2 pairs" draft default is
  withdrawn); 24 tests.
- Protocol corrections: C1 planning counts renamed to normal-approximation
  estimates with an explicit "metric selection must follow semantics, not
  ease of passing" clause; LONGRUN_STEPS corrected 531→**544** (full
  17,398-row dapo-math-17k ÷ GBS 32; the withdrawn claim wrongly cited the
  parent recipe, which targets a different dataset); C2 input fingerprint
  honestly scoped to dataset/seed/token-volume (dynamic batching ≠ exact
  sample order); TRACE requires genuinely overlap-enabled topologies
  (DP4+`--overlap-grad-reduce` primary; TP2×DP2+`--tp-comm-overlap`
  conditional on TransformerEngine); C3 metric renamed EXTERNAL-OBSERVER
  VISIBILITY LATENCY (raw primary, no constant subtraction).
- `CLEAN_ENV_RECOMPUTATION_CHECKLIST.md` restructured: CURRENT STATE /
  HISTORICAL PILOT RECOMPUTATION / CURRENT CORRECTNESS GATE / FUTURE
  CONFIRMATORY PROCEDURE.
