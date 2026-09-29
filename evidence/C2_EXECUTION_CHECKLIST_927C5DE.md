# C2 execution checklist — build `927c5de`

Status: **not executable yet; no `927c5de` C2 arm has started.** This is the
single run sheet for the two independent follow-up experiments declared in
`C2_PARAMETER_PROTOCOL_927C5DE.md` and
`OVERLAP_CALIBRATION_PROTOCOL_927C5DE.md`. It fixes sample order, acceptance
rules, retained artifacts, and the tool gaps found on 2026-09-29. It does not
alter the historical `a48a23b` verdicts: parameter equivalence remains
INCOMPLETE and overlap remains NOT_PASS.

## 1. Non-negotiable entry gate

Before creating a Ray job, create and commit a new immutable execution lock
for each experiment. Each lock pins the clean product SHA
`927c5de2f5a8f307cad0c87f2c7eb2b78262334d`, recipe and dataset SHA256,
environment fingerprint, runner SHA256, analyzer/comparator SHA256, exact
arm order, 48 expected steps, `SAVE=1`, DP4 topology, and the appropriate ON
profile. Every arm manifest must repeat the lock hash and prove identical
driver and worker source hashes, successful job completion, expected steps,
and returned resources.

Before the first arm, make one disposable `SAVE=1` checkpoint and measure its
complete tree size. Free durable storage must be at least
`8 × measured_checkpoint_tree_size × 1.20`, in addition to logs and traces.
Checkpoint trees are retained until the comparison and its public archive have
been hash-verified. A tree hash is an integrity record only; it is not a
parameter-equivalence measurement.

Do not launch if the product tree is dirty, the lock is not committed, the
four GPUs are not exclusively owned, Ray preflight or proxy bypass fails, or
any identity field differs between arms. An interrupted, failed, under-stepped,
or unclean arm is INVALID; it is retained and is never silently replaced.

## 2. Tool readiness gate

The currently committed tools are insufficient for this checklist:

- `tools/c2_lock.py` hard-codes six OFF calibration arms and compares
  checkpoint-tree hashes. It cannot run this four-OFF design or compare tensor
  keys, shapes, dtypes, and values.
- `tools/trace_verdict.py` hard-codes four historical arm names and one
  ON/OFF pair. It cannot evaluate the new four-OFF-plus-two-pair design.

Before GPU work, add tested, non-overwriting successors (or parameterized
versions) that enforce the exact arm orders below, reject missing retained
inputs, write a self-hashed result, and return PASS=0, NOT_PASS/INCOMPLETE=1,
INVALID=2. Commit those tools and tests, then create the locks from their
committed SHAs. Until then this checklist is a blocked protocol, not permission
to run a manually interpreted experiment.

## 3. Parameter equivalence and training correctness

This is an eight-arm experiment, independent of the overlap experiment.

| Phase       | Fixed order                                    | Purpose                                  |
| ----------- | ---------------------------------------------- | ---------------------------------------- |
| calibration | `P-C1-off`, `P-C2-off`, `P-C3-off`, `P-C4-off` | Two OFF/OFF contrasts: C1/C2 and C3/C4   |
| measurement | `P-M1-off`, `P-M1-on`, `P-M2-on`, `P-M2-off`   | Two ON/OFF contrasts in AB then BA order |

Read no ON output until both calibration contrasts complete and the
calibration result has been committed. For each tensor, calibrate
`tol(t) = 2 × max(abs_delta(C1,C2,t), abs_delta(C3,C4,t))`, using float64 CPU
accumulation for the comparison only. The frozen result contains the complete
tensor inventory, tolerance table, two contrast hashes, comparator SHA256 and
its own SHA256. A zero tolerance requires exact equality.

For each ON/OFF pair, the comparator must require equal tensor key sets,
shapes, and dtypes, then record max absolute and relative delta for every
floating tensor. Non-floating tensors compare exactly. PASS requires every
pair to satisfy the frozen tolerance, equal update count, equal token series,
finite loss/gradient series, equal learning-rate series, no NaN/Inf, and all
required final checkpoints. Any breached tensor is NOT_PASS; a missing tree,
tensor payload, lock, or raw log is INCOMPLETE. Do not average tensors or
treat tensors, steps, or shared-arm contrasts as independent samples.

## 4. Overlap experiment

This is a separate eight-arm DP4 experiment with
`--overlap-grad-reduce` enabled and all rank 0–3 traces retained.

| Phase       | Fixed order                                    | Purpose                                  |
| ----------- | ---------------------------------------------- | ---------------------------------------- |
| calibration | `O-C1-off`, `O-C2-off`, `O-C3-off`, `O-C4-off` | Two OFF/OFF contrasts: C1/C2 and C3/C4   |
| measurement | `O-M1-off`, `O-M1-on`, `O-M2-on`, `O-M2-off`   | Two ON/OFF contrasts in AB then BA order |

From only the two predetermined OFF/OFF contrasts, freeze
`delta_overlap = 2 × max(abs(overlap(C1)-overlap(C2)), abs(overlap(C3)-overlap(C4)))`. Commit that result before starting `O-M1-on`.
The analyzer recomputes overlap from SHA256-verified raw Kineto/CUPTI traces;
it must reject duplicate or missing ranks and must preserve the scope of the
sync counter as `cudaDeviceSynchronize` only.

Each measurement pair passes only if its ON overlap ratio is no lower than its
paired OFF ratio minus `delta_overlap`, and ON introduces no additional
`cudaDeviceSynchronize` calls relative to that paired OFF arm. Report per-rank
and aggregate values, all raw-trace hashes, both pair outcomes, and natural
OFF/OFF sync variance. Neither condition supports a claim about all possible
global synchronization. If either pair fails, overlap is NOT_PASS; missing or
unverifiable traces are INCOMPLETE.

## 5. One-shot publication rule

Run exactly the sixteen listed arms once. Never add arms after observing any
calibration or ON result, widen a frozen tolerance, substitute a different
recipe, or reuse an arm across the two experiments. Preserve failed and
invalid manifests alongside valid ones. The final C2 report binds product SHA,
evidence SHA, locks, raw and public artifact hashes, analyzer verdicts, and
limits. C2 is PASS only when both the parameter/training-correctness result
and the overlap result pass; otherwise state their separate verdicts without
relabeling the historical `a48a23b` results.
