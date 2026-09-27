# TASK11 C1 Long-run Confirmatory Protocol (preregistered)

Written and committed BEFORE any long-run data exists. The only prior overhead
data referenced for design is the N=1 short pair (`abba-cac4cb6-run4`), which is
frozen evidence and is not altered by this protocol.

## 1. Motivation and scope

The official criterion 1 is "overall overhead below 0.5 %". The short-arm
campaign (48 optimizer steps per arm, ~13 min per arm at ~15.9 s/step) applies a
fixed profiler start-up cost to a deliberately short denominator: at N=1 the
whole-run per-step mean is +2.222 %, of which the one-off step-1 delta
(+15.699 s) contributes ~2.03 percentage points and the steady-state is
+0.192 %. A short arm therefore measures start-up amortisation as much as it
measures overhead.

This protocol preregisters ONE confirmatory long-run experiment for whichever
build ships (the frozen `cac4cb6` or, if the short campaign fails and the
optimisation phase runs, the `NEW_PRODUCT_SHA`). It does not replace the short
campaign: the final report presents the short campaign and the long-run side by
side, exactly as required.

## 2. Frozen experiment specification

| Parameter | Value | Delta vs short arm |
| --- | --- | --- |
| Recipe | `scripts/training/sft/run-qwen3-0.6B-4xgpu-dp4-observer.sh` | none |
| Optimizer steps per arm | `NUM_ROLLOUT=480` | **the only recipe change** (48 -> 480) |
| SAVE | `SAVE=0` in both arms | none (short arms did the same) |
| GPUs / topology | 4x RTX 4090, DP=4, TP=PP=CP=1 | none |
| Dataset | `dapo-math-17k-sft-256.jsonl` (sha256 `44f9ddac…a59428`) | none |
| Seed | unchanged recipe default | none |
| Profiler env (ON arm) | `RELAX_STRAGGLER_ENABLE=1`, `WINDOW_S=5`, `PERSIST_WINDOWS=3`, `REPORT_INTERVAL_S=10`, `WARMUP_WINDOWS=2`, collector `127.0.0.1:<fresh port>` | none |
| Product SHA | identical in both arms, recorded in the run manifest | — |
| Launch wrapper | `scripts/entrypoint/ray-job.sh` | none |

Step-count justification (declared, not tuned): 480 = 10x the short arm and
~2.1 h of continuous training at the recipe's ~15.9 s/step — a realistic
minimal training session for this recipe class. The count is fixed by duration
realism BEFORE any new-build data exists, and this protocol binds itself to
accept a FAIL at this count.

Arithmetic disclosure (from the frozen N=1 point estimate, for transparency
only): steady +0.192 % plus +15.699 s amortised over 480 x 15.9 s implies
~+0.40 % whole-run for the UNOPTIMISED build. If the short campaign fails and
the start-up cost is legitimately reduced, the same 480 steps apply unchanged.

## 3. Design

- Minimum: one valid OFF/ON pair (order recorded). Target if the machine window
  allows: two pairs in AB/BA order. A pair is valid only if both arms run in
  the same session window with the same fingerprint; one invalid arm invalidates
  the pair. Cross-session pairing is forbidden.
- Each arm is a fresh Ray job submission (fresh processes), same as the short
  campaign.

## 4. Estimators (frozen `evidence/analyze_c1.py`, seed 20260926)

- PRIMARY: whole-run per-step mean delta on `perf/train_time` — every optimizer
  step included, step 1 NOT excluded (whole-run accounting).
- Secondary (reported, never deciding): paired median delta; steady-state
  (excluding step 1); whole-run wall-clock and throughput (total tokens / wall)
  deltas; p50/p95/p99; step-1 (start-up) delta; pair-resample bootstrap CI of
  the primary.
- A run with zero recorded training steps is INVALID, not zero.

## 5. Acceptance rule

C1 = PASS at realistic duration iff the long-run primary (whole-run per-step
mean, all pairs) is < 0.5 % AND the short-campaign result is reported alongside
with its own verdict. If the long-run primary is >= 0.5 %, C1 = FAIL and the
next step is the ACCEPTANCE_OPTIMIZATION_PHASE (real overhead only; no
measurement removal, no stage-count reduction, no workload reduction, no
threshold or estimator change, no baseline shortening). If the optimisation
phase produces a NEW_PRODUCT_SHA, C1, C2 and affected C3 evidence are re-run.

## 6. Evidence

Append-only: per-arm run manifest (run_id, product_sha, pr_head, env_id,
hardware, recipe, dataset sha256, seed, start/end, exit code, verdict, artifact
paths, sha256), raw logs, analyzer output, environment fingerprint. Invalid and
failed runs are kept. The producing commit of this protocol is recorded in the
campaign README.
