# TASK 11 Unified Acceptance Protocol (authoritative; 2026-09-27)

This document is the SINGLE authoritative protocol for the Task 11 acceptance
campaign. Where any earlier document conflicts with it, THIS document governs.
Explicitly superseded clauses:

- `TASK11_FINAL_ACCEPTANCE_PROTOCOL.md` — its arm-validity section ("a run with
  zero recorded training steps is INVALID") is superseded by the full analyzer
  gate below; its per-pair eligibility wording is superseded by "both arms
  VALID + pair fingerprint".
- `TASK11_C2C3_PROTOCOL.md` — its tolerance table stands, except that C2
  evidence is now collected natively inside every C1 arm (below) in addition
  to its dedicated runs.
- `TASK11_C1_LONGRUN_PROTOCOL.md` — stands unchanged except: the analyzer is
  now the gated version, and the long-run verdict is reported ALONGSIDE the
  short campaign, never instead of it.

## 1. Pinned versions (EXACT; a run is only valid against these)

A formal experiment is valid only against the exact versions below. If the product,
analyzer, protocol, recipe, data or environment changes mid-campaign, the already-run
arms are retained with an explicit note on why they stopped being valid; pass
conditions are never redefined after seeing data. Every arm manifest must carry the
preregistered identity fields (product commit, dataset sha256, recipe, expected steps,
environment fingerprint, seed-bearing config) — the analyzer checks arms against THIS
checklist, not merely OFF-vs-ON equality (both arms missing a field, or six pairs from
six builds, are rejected).

| Component | Version |
| --- | --- |
| Product code | `e961661bbdf662016a658d0fc2283d200a899a96` on `feat/task11-straggler-profiler` (EXACT; a code change starts a new experiment version — the old data is retained with a note on why it stopped being valid, and pass conditions are never silently redefined) |
| Analyzer | `evidence/analyze_c1.py` at evidence-branch commit `0ef6badf1b6112b14f47d76d140b1fc55de56016` (EXACT; full eligibility gate incl. fingerprint presence and campaign single-version; `test_analyze_c1_gate.py` 27 tests green) |
| Recipe | `scripts/training/sft/run-qwen3-0.6B-4xgpu-dp4-observer.sh`, `NUM_ROLLOUT=48` (short) / `480` (long), `SAVE=0` both arms |
| Dataset | `dapo-math-17k-sft-256.jsonl`, sha256 `44f9ddacd1e078d60d1a65d43dda76283b5ba68c6db7bbd54462126cd6a59428` |
| Environment | 4x RTX 4090, driver 595.71.05, ray 2.58.0, torch 2.8.0+cu128, python 3.12.3 (venv `/root/autodl-tmp/megatron-stack/venv`); re-captured per campaign start |

## 2. The two experiments answer different questions

- **Short campaign (6 AB/BA pairs, 48 steps/arm).** Question: what does the
  profiler cost on the recipe's own duration, including its fixed start-up?
  Reports the whole-run per-step mean, the start-up/steady split, wall clock,
  throughput, p50/p95/p99.
- **Long-run confirmation (480 steps/arm, 1-2 pairs).** Question: does the
  whole-run overhead stay under bound at a realistic training duration? Same
  estimators, preregistered step count fixed BEFORE any long-run data exists.
- The long-run can NEVER override a short-campaign failure; both are reported
  side by side. N=1 anywhere is a conditional point estimate only.

## 3. Primary metric, validity, statistics (frozen)

- PRIMARY: whole-run per-step mean delta % on `perf/train_time`, every step
  included, mean across pairs. Secondary (reported, never deciding): paired
  median, steady-state (excl. step 1), wall-clock and throughput deltas,
  p50/p95/p99, start-up delta, pair-resample bootstrap CI (seed 20260926).
- Arm validity = the analyzer gate: manifest valid, exit 0, PREREGISTERED step
  count, exact step-ID set, complete metric series, ON-arm observation
  evidence (envelopes >= 1). Pair eligibility = both arms VALID + identical
  commit/dataset/recipe + profiler on exactly the ON arm + exact alignment.
  A/A controls pass the same gates.
- PASS: >= 6 eligible pairs AND estimate < 0.5 % AND bootstrap upper < 0.5 %.
  NOT PASS: estimate >= 0.5 %. INCONCLUSIVE: fewer pairs, or CI too wide.
  Median/steady/p50 below 0.5 % alone NEVER yields PASS.

## 4. C2 evidence is collected inside every C1 arm

Each C1 arm additionally records, from the training log natively: loss values
per step, actual optimizer updates (weight-update events), NaN/Inf occurrences
(if any), and the per-rollout reward metrics. The OFF/OFF noise floor comes
from A/A arms under the same gates. Dedicated loss-pair and overlap-trace runs
are SEPARATE from the overhead arms (an nsys/torch-profiler trace is never
mixed into an overhead measurement arm).

## 5. C3 evidence

Real verdicts with the full fact set (rank, raw/coarse stage, observed and
reference ms, gaps, deltas, tokens, coverage, measurement kind, facts,
candidate causes, persistence) demonstrated on a real training run, plus the
schedule-dependent delay distribution (p50/p95/p99) and the platform path
(ingest -> verdict -> reporter -> existing perf merge -> existing platform
write). MUST cover the tail-window case: the last batch of samples with no
later envelope — whether a verdict still closes the window, and what flush()
costs. The "realtime" operational definition remains the pending mentor
decision (RFC #357); no E2E-latency claim beyond the schedule-dependent delay
is made.

## 6. Machine recovery: two INDEPENDENT incidents (both documented)

1. 2026-09-26: CUDA-in-Ray worker kills (5-17 s after CUDA init) — eliminated
   matrix, reproducer and re-entry gates in `env_incident_20260926_evening/`.
2. 2026-09-27: platform-proxy hijack of intra-container HTTP after the
   overnight container reschedule (<previous-container-private-ip> -> <current-container-private-ip>; `no_proxy` lacked
   the container IP) — §8 of the same report. Fixing the proxy does NOT
   retroactively explain incident 1; they are separate causes.

## 7. Pre-run checklist (fresh every campaign; stale conclusions are never reused)

1. G1 GPU/foreign-process audit; G2 out-of-Ray CUDA canary >= 150 s; G3 m1
   reproducer x3; G4 canary7; G5 three fresh Ray CUDA workers >= 120 s.
2. **Worker env probe**: from an ACTUAL Ray worker, verify (a) no proxy env
   or a `no_proxy` covering the container IP, and (b) direct HTTP reachability
   of internal endpoints (dashboard + engine port) without the proxy.
3. Exclusive-resource ownership manifest (head/dashboard/job PIDs, ports, temp
   dir, GPUs); kills only by explicit PID from the manifest.
4. OFF/ON/OFF smoke (3-5 optimizer steps each): training advances, loss
   finite, clean shutdown, GPU release; ON additionally: envelopes judged,
   late = 0, forward-backward coverage, no unexplained drops.
5. Only then does the campaign start; Task 4 does not touch the GPUs during it.
