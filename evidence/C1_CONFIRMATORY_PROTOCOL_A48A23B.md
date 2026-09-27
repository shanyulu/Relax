# C1 confirmatory protocol — build `a48a23b` (preregistered)

Status: **pre-registered before any confirmatory data exists.** This document
supersedes, for the current build, the long-run protocol written for `cac4cb6`
(that file remains as frozen history; the build moved through `e961661` and
four correctness fixes to `a48a23b`, which closes the old campaign namespace).

## 1. The existing 6-pair campaign is a PILOT — final label

The `e961661` 6-pair AB/BA campaign (`gpu_campaign/abba-e961661-run1`, evidence
`4a9e751`) is relabelled **PILOT / FIRST CAMPAIGN**. Its verdict remains
INCONCLUSIVE-wide-interval and is not re-judged. Its data is used for exactly
one thing: designing the confirmatory experiment below. The S1-off vs S2-off
contrast in older analyses is renamed **cross-session OFF/OFF diagnostic
contrast** — it is NOT an A/A noise floor (an A/A requires an independently
preregistered OFF/OFF paired design; see §6).

Pilot pair-level statistics (recomputed 2026-09-27 from the archived job
logs — exact, not quoted):

| Metric (per-pair whole-run Δ%) | mean | SD | values |
| --- | --- | --- | --- |
| `perf/train_time` (metric option A) | +0.4174% | 2.4028% | +2.177, +1.779, −2.308, +2.433, +1.393, −2.970 |
| whole-job wall-clock (metric option B) | +0.0656% | 0.9719% | +0.536, +0.722, −0.353, +0.342, +0.865, −1.718 |

## 2. Primary-metric decision is a mentor decision, not ours

The official criterion reads "**整体**性能开销低于 0.5%". Two readings are
defensible and the choice changes feasibility by two orders of magnitude
(sample size for a one-sided 95% CI upper bound < 0.5%, i.e.
N = ceil((1.645·SD/0.5−mean)²) with pilot SD/mean):

| Option | Primary metric | Supporting | Approximate planning pair count (one-sided / two-sided) | Feasible? |
| --- | --- | --- | --- | --- |
| A | `perf/train_time` whole-run mean Δ% | wall, throughput, startup, steady-state | ≈2,292 / ≈3,253 | **No** (≈4,000–5,400 GPU-hours at ~13 min/arm) |
| B | end-to-end whole-job wall-clock Δ% (throughput as the dual) | `perf/train_time` as component metric | ≈14 / ≈20 | **Yes** (≈7–9 GPU-hours) |

These pair counts are **normal-approximation planning estimates** computed as
N ≈ ceil((z·SD/(0.5−μ))²) from the pilot μ/SD (z=1.645 one-sided, 1.96
two-sided), valid only for μ<0.5. They are NOT exact required sample sizes,
NOT guaranteed power results, and NOT bootstrap-exact — they exist solely to
compare resource cost between options. **Feasibility estimates are shown only
for resource planning; metric selection must follow the intended meaning of
"overall overhead", not which metric is easier to pass.** The mentor selects
the metric on semantics. Under option A the 0.5% bound is statistically
indistinguishable from the pilot's noise at any feasible N; under option B it
is confirmable. Both facts are reported to the mentor without a
recommendation. A merged
decision request (metric A/B, realtime reading, attention/MoE scope) is posted
once on RFC #357. **No confirmatory campaign launches before the metric
choice is answered.** If the mentor changes the metric after a campaign ran,
that campaign stands as history and a new protocol is preregistered; old data
is never relabelled.

## 3. Frozen confirmatory specification (parameterised by the metric choice)

| Parameter | Value |
| --- | --- |
| PRODUCT_SHA | `a48a23ba5a39b3410a19e91d5f362154d97c9977` (clean tree; enforced by `tools/campaign_lock.py`) |
| Recipe | `scripts/training/sft/run-qwen3-0.6B-4xgpu-dp4-observer.sh`, SAVE=0 (timing arms), 4×RTX4090, TP1/DP4 |
| Dataset | `dapo-math-17k-sft-256.jsonl`, sha256 `44f9ddac…a59428` |
| Arm length | 48 optimizer steps (short arms, identical to pilot) — **plus** one long-run arm pair (§4) |
| Pair order | AB/BA balanced, sessions numbered from the next unused integer (S7…), exact order committed in CAMPAIGN_LOCK.json |
| N (pairs) | Fixed in CAMPAIGN_LOCK before launch from the chosen option's planning estimate: **Option A:** 2,304 (explicitly recorded as infeasible; do not launch without mentor sign-off on cost). **Option B:** 24 (20 two-sided + 4 margin). Both are normal-approximation planning counts, not exact requirements |
| Stopping rule | NONE. Fixed N, one shot. No interim looks, no "add pairs until the CI shrinks". A failed/inconclusive confirmatory run triggers the preregistered optimization phase (new PRODUCT_SHA, new lock, full affected rerun), not more sampling |
| Analyzer | `evidence/analyze_c1.py` @ its committed sha (in CAMPAIGN_LOCK) |
| Bootstrap | pair-level, 10,000 resamples, seed 20260926 |
| ACCEPTANCE_RULE | PASS iff session-level whole-run estimate < 0.5% AND bootstrap 95% CI upper < 0.5%; median-only/steady-only never PASS; N=1 ⇒ INCONCLUSIVE |
| Pre-arms | OFF→ON→OFF smoke at the locked SHA (SMOKE_GATE), then startup decomposition (§5) |

## 4. Long-run arm — natural horizon, fixed before running

| Parameter | Value |
| --- | --- |
| REFERENCE_RECIPE | `scripts/training/sft/run-qwen3-0.6B-4xgpu-dp4-observer.sh` itself, pointed at the FULL dataset (its own 256-row default is the short-arm subset) |
| REFERENCE_DATASET | `zhuzilin/dapo-math-17k` (HF snapshot `2e656129…`), the dataset family the recipe's short-arm JSONL was derived from via `tools/straggler/make_sft_dataset.py` |
| REFERENCE_DATASET_SIZE | **17,398 rows** (counted 2026-09-27 from the snapshot's `dapo-math-17k.jsonl`) |
| GLOBAL_BATCH_SIZE | 32 |
| NATURAL_HORIZON | ⌈17,398/32⌉ = **544 optimizer steps** for one epoch (543 full batches + one 22-sample partial final batch; the loader's actual drop/partial behaviour is recorded from the arm's own step count at run time and the manifest is authoritative) |
| WHY_REPRESENTATIVE | one epoch over the recipe's own full dataset is the dataset's natural training horizon; the earlier "parent recipe natural epoch" claim was wrong (the parent script targets OpenMathReasoning-mini, a different dataset) and is withdrawn. 544 is derived only from dataset size ÷ batch size — independent of any observed threshold, and NOT chosen to amortise startup |
| LONGRUN_STEPS | 544 (one OFF/ON pair, AB/BA order randomised by coin flip recorded in the lock) |
| Reporting | long-run and short-run results are reported side by side; the long-run NEVER overwrites a short-run failure or inconclusive verdict |

## 5. Startup decomposition (before any confirmatory arm)

Run `tools/straggler_startup_decompose.py` (already preregistered by
`TASK11_STARTUP_DECOMPOSITION.md`) OFF/ON with fresh processes; report
shim_init_ms, event_pool_ms, observer_start_ms, collector_bind_ms,
first_sample_ms, first_window_ms, first_step_ms. Only a REPRODUCIBLE
profiler-attributable startup delta may later justify profiler-startup
optimisation (which would be a new PRODUCT_SHA and full affected rerun).

## 6. A/A noise floor (optional, only if the mentor picks option B)

If option B is chosen, an independently preregistered OFF/OFF paired design
(≥8 pairs, same lock discipline) MAY be run to establish a true A/A
noise floor for the wall-clock metric. It is not required for the verdict
(the bootstrap CI already carries pair-level variance) and must not be
substituted for it.

## 7. Prohibited

- Sequential sampling of any kind (run → look → extend).
- Choosing LONGRUN_STEPS to amortise startup past 0.5%.
- Relabelling pilot data as confirmatory, or pooling pilot + confirmatory
  into one verdict.
- Changing metric after seeing confirmatory results.
