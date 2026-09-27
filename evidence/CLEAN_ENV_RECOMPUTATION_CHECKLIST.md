# Clean-environment recomputation checklist (pre-merge)

Purpose: a maintainer with no access to this machine can recompute the key
claims from public artifacts only. Every item lists the exact inputs, command,
and expected output. Anything not recomputable this way is labeled as such in
EVIDENCE.md rather than claimed.

Structure (so history stays recomputable while the build moves):
CURRENT STATE → HISTORICAL PILOT RECOMPUTATION → CURRENT CORRECTNESS GATE →
FUTURE CONFIRMATORY PROCEDURE.

## 0. Pins and checkouts

### CURRENT STATE (2026-09-27)

- Task 11 product / PR head: `a48a23ba5a39b3410a19e91d5f362154d97c9977`
  (four correctness/launcher commits on top of the pilot build `e961661`).
- Task 4 product: `0481701`; PR #370 head is docs-only on top.
- Evidence branch: current head of `evidence/task11-straggler`.
- The `e961661` 6-pair campaign below is the PILOT (INCONCLUSIVE); it is NOT
  the final-code performance result and is not relabelled as such.
- Mentor decisions pending: C1 primary-metric reading (A/B), realtime
  definition (Decision A), attention/MoE scope (Decision B) — see RFC #357.

- Product (Task 11): `e961661bbdf662016a658d0fc2283d200a899a96`
- Product (Task 4): `0481701` (PR #370 head `5b512d0` is docs-only on top)
- Evidence branch: `evidence/task11-straggler` (protocol @ `f9976f8`, formal
  campaign + analyzer fix @ `4a9e751`, this checklist's commit)

Two checkouts are needed (product repo at the pinned SHA, plus this evidence
branch):

```
git clone https://github.com/shanyulu/Relax.git product && cd product
git checkout e961661bbdf662016a658d0fc2283d200a899a96
git clone -b evidence/task11-straggler https://github.com/shanyulu/Relax.git evidence
```

## HISTORICAL PILOT RECOMPUTATION (build `e961661`; stays valid as frozen history)

## 1. Task 4 artifact integrity (no GPU, ~1 min)

```
sha256sum demos/task4_genrm/results/train_continuity_20260925_r5/raw_job_driver.log
```
Expected: `feb23ecc80d3ce7382cefd68ca32aea20c5c26f3057978a272c0b40f44dfec78`
(recorded alongside as `raw_job_driver.log.sha256`).

## 2. Task 4 machine-generated reports regenerate byte-for-byte (no GPU, ~1 min)

Run from the product checkout, where the archived results directory lives:

```
cd demos/task4_genrm/results/train_continuity_20260925_r5
python3 reanalyze_three_timelines_v2.py     # rewrites reanalysis_v2.json
python3 render_reanalysis_v2.py             # rewrites REANALYSIS_V2.md (v2.1)
python3 test_timeline_parsing.py            # 13 passed
git diff --stat                            # both files unchanged
```
Expected: pure log parsing with no timestamps embedded; both outputs are
byte-identical to the archived copies. The v2.1 renderer computes the
window-boundary crossings (step-start 75 s spans scale-out; execution-end
29 s spans scale-in; rollout 76 s crosses the scale-out completion boundary)
instead of asserting them.

## 3. Task 11 targeted test suite at the pinned product SHA (no GPU, ~1 min)

The CI-shaped environment blocks the `megatron` package the same way the
GitHub CPU runner does. The blocking plugin ships on the evidence branch:

```
cd <product checkout at e961661>
PYTHONPATH=<evidence checkout>/evidence/tools \
  python3 -m pytest tests/utils/straggler/ -p ci_block_megatron -q
```
Expected: **374 passed, 2 skipped** (verified 2026-09-27 at `e961661`).

## 4. Task 11 gated analyzer verdict reproduces (no GPU, ~1 min)

```
cd <evidence checkout>
python3 evidence/analyze_c1.py \
  --campaign evidence/gpu_campaign/abba-e961661-run1 \
  --expected-steps 48 \
  --out /tmp/verdict.json
```
Required parameter: `--expected-steps 48` (the manifests carry no
pre-registered step count; the protocol's preregistered value is 48).
Expected: verdict `INCONCLUSIVE-wide-interval`; session-level whole-run mean
`+0.4174268001623327%`; bootstrap 95% CI `[-1.294897986616048%,
+2.022764799538646%]` (10,000 pair-level resamples, seed `20260926` —
deterministic, so agreement is exact).

## CURRENT CORRECTNESS GATE (build `a48a23b`, no GPU)

```
git checkout a48a23ba5a39b3410a19e91d5f362154d97c9977
PYTHONPATH=<evidence>/evidence/tools python3 -m pytest \
    tests/utils/straggler/ tests/tools/test_ray_job_preflight.py \
    tests/tools/test_task11_recipe_overrides.py -p ci_block_megatron -q
```
Expected: **411 passed, 2 skipped** (verified 2026-09-27). The D1/D2
old-fail record (6 failed on `e961661`) is in `D1_D2_CORRECTNESS_GATE.md`.
Campaign-lock and two-stage-C2 tooling tests:
`python3 -m pytest evidence/tools/test_campaign_lock.py evidence/tools/test_c2_lock.py -q`
(expected 17 + 24 passed; the validator's own old-fail record is 11 of 16
corruption tests wrongly VALID on the pre-hardening validator).

## 5. Pilot campaign recompute (4x RTX 4090, ~1.2 h, optional, build `e961661` only)

Inputs are public: HF model snapshot `Qwen/Qwen3-0.6B` + the dataset JSONL
committed at `scripts/training/sft/data/dapo-math-17k-sft-256.jsonl`
(sha256 `44f9ddacd1e078d60d1a65d43dda76283b5ba68c6db7bbd54462126cd6a59428`).
Run the archived driver with a proxy-free Ray cluster:

```
cd <evidence checkout>
RAY_ADDRESS=<head-node>:6379 python3 evidence/gpu_campaign/abba-e961661-run1/driver.py
```
(The driver pins the product SHA `e961661`, the recipe, AB/BA arm order
S1..S6, and the output layout; it refuses to start on a dirty tree.)
Expected: verdict CATEGORY unchanged (INCONCLUSIVE family); the point
estimate lands within the archived bootstrap CI. This is the only item that
needs GPUs.

## FUTURE CONFIRMATORY PROCEDURE (not yet run; preregistered)

- C1 confirmatory: `C1_CONFIRMATORY_PROTOCOL_A48A23B.md` — launches only
  after the mentor picks the primary metric (A/B); fixed N, no stopping rule;
  long-run = 544 steps (one epoch of the full 17,398-row dapo-math-17k at
  GBS 32).
- C2: `C2_PROTOCOL_A48A23B.md` + `tools/c2_lock.py` — calibration lock →
  6 OFF arms → frozen result → measurement lock → ON/OFF pairs.
- Traces: `TRACE_PROTOCOL_A48A23B.md` — overlap-ENABLED topologies only.
- C3: `C3_HARNESS_DESIGN_A48A23B.md` — external-observer visibility latency.

## Items NOT recomputable from public artifacts (labeled as such)

- Per-sample rollout JSONLs (rotated away on the runner; log lines + SHA256
  are the durable record)
- Task 11 r5/r6 engine-attribution runs and the post-fix smoke arms
  (runner-local HF cache paths; commands and raw logs archived instead)
