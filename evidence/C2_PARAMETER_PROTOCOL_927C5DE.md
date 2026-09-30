# C2 parameter-equivalence protocol — build `927c5de` (preregistered)

Status: **pre-registered before any `927c5de` C2 data exists.** This is the
follow-up demanded by `REVIEW_CORRECTIONS_20260927.md` item 2: at `a48a23b`
the C2 comparison was INCOMPLETE — 0 metric violations, 2 missing
`parameter_equivalence` evidence items — because the old runner's
hash-and-prune destroyed the checkpoints and a loss envelope is not a
parameter comparison. Product chain: `a48a23b` → `293390e` → `4654e5a` →
`f120aa8` → `927c5de` (confirmed-alert metrics, quiet summary reads, state-lock
isolation). The affected-acceptance declaration is in PR #378: C2 parameter
equivalence must be re-established on this build; the `a48a23b` INCOMPLETE
verdict stands as version-pinned history.

GPU access and the 320 GiB storage gate were restored on 2026-09-30; no formal
parameter arm had started when this wording was updated. The design and
decision rule below are unchanged. Nothing in this document may be edited
after the first `927c5de` C2 arm starts (lock-before-see).

## 1. Inputs (fixed)

- Checkpoints retained: both arms run SAVE=1; the runner
  (`tools/run_c2_campaign.py`) no longer auto-deletes checkpoints. A missing
  or incomplete checkpoint yields **INCOMPLETE**, never a pass.
- Per-tensor extraction from the final Megatron checkpoint of each arm:
  key set, shape, dtype, and a float payload per tensor (CPU, float64
  accumulation).
- The same `tools/extract_c2_native.py` loss/grad/lr/token series as the
  `a48a23b` protocol (unchanged secondary checks).

## 2. Measured quantities (nothing added post hoc)

| Quantity                 | Definition                                                         |
| ------------------------ | ------------------------------------------------------------------ |
| key/shape/dtype equality | set equality over (name, shape, dtype) triples across the two arms |
| per-tensor max abs delta | max                                                                |
| per-tensor max rel delta | max                                                                |
| exact-equal tensor count | # tensors with bit-equal payloads                                  |
| envelope tolerance table | per-tensor tolerance, frozen from calibration (§3)                 |

## 3. Calibration first, then measurement (freeze-before-see)

1. **OFF/OFF calibration pair(s)** at `927c5de` (≥2 pairs, AB/BA). The
   per-tensor tolerance for tensor *t* is
   `tol(t) = 2 × max over calibration contrasts of per-tensor max-abs-delta(t)`.
   **Statistical unit: one pairwise contrast between two arms.** Contrasts
   share arms and are NOT independent samples; step-level or tensor-level
   counting as "samples" is forbidden (the withdrawn `720 delta samples`
   phrasing from the `a48a23b` protocol is superseded by this clause). This
   is an envelope over worst-case same-build noise, not a confidence interval.
2. The tolerance table is hashed into a calibration result and referenced
   (SHA-256) by the measurement lock, produced by
   `tools/c2_parameter_campaign_927c5de.py`. Both locks also pin the reviewed
   DCP adapter and comparator code hashes. The comparison tool is committed
   BEFORE any ON arm runs; no tolerance may be widened afterwards.
3. **ON/OFF measurement pair(s)** (≥2, AB/BA, same everything else).

## 4. Decision rule (fixed)

- **PASS** iff: key/shape/dtype triples equal AND every tensor's ON/OFF
  max-abs-delta ≤ its frozen tolerance.
- **NOT PASS** on any breach; the report names the tensors, their deltas and
  tolerances.
- **INCOMPLETE** if any input is missing (checkpoint, series, lock); exit
  code non-zero for NOT PASS and INVALID, per the strict-gates CLI contract.
- Fixed N, one-shot: exactly the preregistered arms run; no additions after
  seeing results ("no run-until-pass").
