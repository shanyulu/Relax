# C2 correctness protocol — build `a48a23b` (preregistered)

Status: **pre-registered before any new C2 data exists.** Supersedes for this
build the `cac4cb6` C2/C3 protocol (kept as history). The historical
`e961661` loss audit (frozen OFF band → 50/288 ON/OFF steps outside, held-out
OFF/OFF 5/48 and 6/48) is NOT evidence of observer harm or safety: the loss
rule was not passed and the difference was not attributable. This protocol is
the path to an attributable answer.

## 1. Measured quantities (fixed; nothing added post hoc)

| Quantity | Source |
| --- | --- |
| loss trajectory (per optimizer step) | Megatron training log lines (`train N:` native block), extracted by `tools/extract_c2_native.py` |
| optimizer step/update count | `perf N:` record count AND the checkpoint's iteration field (cross-checked) |
| NaN/Inf | numeric-context scan of loss/grad/lr series (bare tokens in numeric context only) |
| learning rate | per-step `train/lr-*` |
| grad norm | per-step `grad_norm` |
| input/microbatch fingerprint | per-step `perf/actor_train_tokens` series + dataset sha256 |
| checkpoint equivalence | final-checkpoint parameter comparison (below) |

## 2. Checkpoint comparison (the pilot could not do this: SAVE=0)

- C2 arms run with **SAVE=1** in BOTH arms (identical saving behaviour;
  saving is not the varied factor).
- After each arm: collect the final Megatron checkpoint; compare OFF vs ON
  parameter-by-parameter.
- If the training path is bit-deterministic under fixed seed (established by
  an OFF/OFF pair FIRST — §3), the comparison is **exact**: per-tensor
  sha256, all tensors, plus optimizer-state and RNG-state hashes.
- If OFF/OFF shows the path is NOT bit-deterministic, the comparison falls
  back to the frozen numerical tolerances of §3 — declared now, before any
  ON data is seen: per-tensor `max_abs_diff` and relative-to-norm bound with
  δ = 10× the OFF/OFF 99th percentile of the same statistic (measured on the
  calibration pairs, frozen into the CAMPAIGN_LOCK before ON runs).

## 3. Order of execution (freeze-before-see, enforced)

1. **≥2 OFF/OFF calibration pairs** at the locked build (SAVE=1). Freeze:
   the loss band, grad-norm band, and (if non-deterministic) the tolerance
   table. Commit the frozen JSON (`tools/audit_c2_loss.py freeze` semantics:
   the freeze phase never opens ON logs).
2. **≥2 ON/OFF pairs** (SAVE=1, same everything else). Extraction with
   `tools/extract_c2_native.py` + `tools/audit_c2_loss.py compare`.
3. **Checkpoint comparison** per §2.
4. **Overlap traces** per `TRACE_PROTOCOL_A48A23B.md` (separate arms).

A single 8-step OFF/ON pair (like the post-fix smoke) validates the
collection chain ONLY; it is never C2 evidence. Minimum formal C2 population:
2 calibration pairs + 2 measurement pairs, all under one CAMPAIGN_LOCK.

## 4. Verdict rules (frozen)

- C2 PASS requires ALL of: loss/grad/lr within the frozen OFF/OFF-derived
  bands (or exact checksum equality if deterministic), equal update counts,
  zero numeric NaN/Inf, checkpoint equivalence per §2, overlap per the trace
  protocol, zero new global syncs.
- Any violation: C2 = NOT PASS, with the violating quantity named. If the
  violation also appears OFF/OFF (calibration pairs show the same behaviour),
  the result is recorded as NOT-ATTRIBUTABLE-to-observer and the protocol
  demands root-cause investigation (e.g. known non-deterministic
  backward/gradient aggregation) BEFORE any retry — the pilot's step-1
  grad_norm divergence pattern is the standing example.
- No tolerance may be widened after seeing ON data. A wrong tolerance is a
  new preregistration; the old result stands.

## 5. Explicitly not claimed

- "No NaN in the log" is not "loss all finite" — only the extracted series
  count.
- Token-series equality is input-volume equality, not sample-content/order
  equality; the dataset sha256 plus the seed pin content and order.
- Historical `e961661` loss data is not promoted to `a48a23b`; the campaign
  namespace is closed.
