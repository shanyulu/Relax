# Overlap calibration protocol — build `927c5de` (preregistered)

Status: **pre-registered before any `927c5de` overlap data exists.** Follow-up
to `REVIEW_CORRECTIONS_20260927.md` item 3: the `a48a23b` overlap verdict is
NOT_PASS (ON fell short of the frozen OFF reference envelope by 6.2e-5) and
stands as version-pinned history — it is not widened, reinterpreted or
re-run to a different answer. The open question is whether cross-session
variance (the observed OFF drift 4.3e-4 exceeded the frozen envelope 9.1e-5)
explains the miss; that is answered by an **independent calibration session**
on the new build, not by editing the old tolerance.

Execution deferred until GPU access; frozen before first data.

## 1. Design

- Topology: DP4 + `--overlap-grad-reduce` (the TRACE_PROTOCOL primary;
  NCCL-confirmed overlap-enabled). Unique rank coverage (0–3) enforced per
  arm; traces retained in-repo per the `b9c01f2` precedent, hash-ledgered.
- **Calibration phase:** ≥2 OFF/OFF pairs (4 OFF arms) in one fresh session
  at `927c5de`. Freeze `delta_frozen' = 2 × max |OFF/OFF pairwise overlap_ratio delta|` over this new population. Statistical unit: the
  pairwise contrast between two arms (contrasts share arms; no
  step/rank-level "sample" counting).
- **Measurement phase:** ≥2 ON/OFF pairs (AB/BA), same session, same recipe,
  everything else identical.
- Metrics per arm: `overlap_ratio` (arm-level aggregate, TRACE_PROTOCOL
  definition, recomputed from hash-checked raw traces by
  `tools/trace_overlap_metrics.py` / `tools/trace_verdict.py`) and
  `cudaDeviceSynchronize` count (context only; the sync counter covers that
  API alone and supports no broader "no new synchronisation" claim).

## 2. Decision rule (fixed)

- **PASS** iff `overlap_ratio(ON) ≥ overlap_ratio(OFF reference) − delta_frozen'` for the new session's own frozen envelope, where the OFF
  reference is the new session's OFF arms.
- **NOT PASS** otherwise; the report shows both sessions' envelopes side by
  side and never mixes them.
- The new verdict is a statement about `927c5de`; it does not retroactively
  change the `a48a23b` NOT_PASS.

## 3. Stopping rule

Fixed N, one-shot: exactly the preregistered arms (4 OFF + 2 ON/OFF pairs
minimum) run; no arms are added after any result is read. A session that
cannot complete its preregistered arms reports INCOMPLETE, not a verdict.
