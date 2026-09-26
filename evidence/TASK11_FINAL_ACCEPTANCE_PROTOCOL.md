# Task 11 — Fused Final Acceptance Protocol

Merged from the two governing directives (21-section + 22-section). Where they overlapped,
the stricter rule wins; where they conflicted, the resolution is written inline as **RESOLVED**.
This file is the single source of truth for the final phase. Product code is frozen.

```
PRODUCT_CODE_SHA = cac4cb6447154e6ae4f563eabab7fecf43dba790
PRODUCT_FREEZE    = unless GPU acceptance exposes a new P0/P1/P2 correctness defect
```

---

## 0. Hard boundaries (non-negotiable)

| Rule | Source |
|---|---|
| No `kill`/`pkill`/`killall` of any process not provably Task 11's | both |
| No deleting other tasks' `/tmp/ray`; no stopping Task 4 Serve/SGLang; no restarting a shared Ray cluster | §1 |
| Do not start a formal acceptance arm unless the 4 GPUs are exclusive | §1 |
| No product-code change without a demonstrated new P0/P1/P2 defect | freeze |
| No rebase / force-push / squash | earlier |
| Never weaken, delete, xfail or skip a test as a fix | earlier |
| No PASS without real evidence; PARTIAL is a valid terminal state | §20 |
| Touch only: own fork/branch, Draft PR #378, RFC #357 | earlier |
| Never write `median < 0.5%` alone, nor "mean is an outlier so ignore it" | §8 |

**RESOLVED (conflict):** the 21-section directive allowed a "downgrade to PARTIAL" ending;
the 22-section directive forbids it (§18: PARTIAL is an intermediate state, not the goal).
**The 22-section rule governs**: continue to real closure unless GPU resources are provably
unavailable, or the maintainer explicitly accepts a mechanism-PR with evidence deferred, or the
official deadline forbids further experiments.

---

## 1. Immediate pre-flight (done)

Environment snapshot recorded 2026-09-26T16:54:03+08:00:
HEAD `cac4cb64…`, `git status` empty, 4× RTX 4090 all 4 MiB used / 0 % util, **no GPU compute
processes**, Ray 1 active node, RUNNING jobs 0 ⇒ **exclusive**.

If a foreign process had appeared: STOP, report owner/process, do not self-clean.

---

## 2. Clean Task 11 Ray lifecycle

Before the campaign: archive the existing Ray logs, failed-job logs and Serve error logs, then
start a **fresh Task 11-owned** Ray environment. Do not inherit the old dashboard/job state, the
`Invalid Ray address` path, the `Deploying application actor failed` path, or the `01000000`
driver-id confusion.

**RESOLVED (address semantics, §10 + §2):** the two address roles are kept distinct:
- dashboard / job API → `http://127.0.0.1:8265`
- runtime / GCS → taken from the **actual `ray start` / launcher output**, never guessed.

Do not merge them into one `RAY_ADDRESS`. If an arm exits non-zero, capture the full stderr,
`ray job status` and the Serve actor traceback and root-cause the **first real exception** before
changing anything. "Try another address" is forbidden.

---

## 3. Dual smoke gate (before any formal arm)

OFF 3–5 steps and ON 3–5 steps, each in a fresh process. Both must show:

```
training step > 0 · loss finite · Serve deployment succeeded · Ray job SUCCEEDED
ON: collector started · observer started · late = 0 · forward-backward judged
clean shutdown · all GPU memory released · a second fresh process starts
```

Any failure ⇒ **STOP**, fix infra or product defect first. Never spend a formal session.

---

## 4. Configuration freeze (at campaign start)

Once the formal C1 protocol starts, none of these may change: recipe, dataset, seed, GPU set,
step count, warmup, profiler config, threshold, window, poll interval, readout timeout, collector
config, statistical estimator, acceptance threshold. Record a **config hash**.

---

## 5. Criterion 1 — paired campaign

`>=6 independent fresh-process pairs`, AB/BA balanced:

```
P1 OFF→ON   P2 ON→OFF   P3 OFF→ON   P4 ON→OFF   P5 OFF→ON   P6 ON→OFF
```

Each arm: fresh process, fresh Ray job, same 4 GPUs, same recipe/data/seed/steps; **only
`RELAX_STRAGGLER_ENABLE` differs**. Between arms confirm: previous training process exited,
Serve application cleaned, VRAM released, no residual collector/observer, Ray healthy.
A single long-lived process flipping an env var is **not** an independent pair.

**Statistical unit = pair/session, never the optimizer step.** Never treat hundreds of steps as
hundreds of independent samples.

Per arm capture: wall start/end, whole-run wall, training wall, throughput, per-step
`perf/train_time` and `perf/actor_train_time`, step-1 startup, steady state, p50/p95/p99,
mean/median/max, GPU utilization, and the ON-side envelope counters (envelopes, judged, late,
duplicate, invalid, drops, readout_timeouts, pool exhaustion, collector errors, verdict count).
Raw JSON/log retained.

Report at minimum: N pairs; per-pair whole-run delta, throughput delta, step-time mean delta,
median delta; session-level median and mean; session-aware/bootstrap CI; startup cost;
steady-state estimate.

**Preserved first pair (must not be overwritten or deleted):** `cac4cb6` whole-run per-step mean
**+2.222 %**, paired median **+0.195 %**, steady-state excl. step 1 **+0.193 %**, startup
**+15.699 s**.

### C1 verdict rule (§8, strict)

The official requirement is **overall < 0.5 %**, so the verdict centres on **whole-run wall
clock, throughput and total training cost**.

- `steady-state < 0.5 %` alone ⇒ **not PASS**
- `median < 0.5 %` alone ⇒ **not PASS**
- If short-run one-off startup pushes overall ≥ 0.5 % ⇒ **stay PARTIAL and say so**

Permitted: a **pre-registered confirmatory long-run** experiment, frozen (code, recipe, fixed
step count, estimator, threshold) *before* seeing its result, existing only to answer what the
one-off startup amortises to in a real long training. It may **not** overwrite a failed short
run — it is additional product-scale explanation only.

---

## 6. Criterion 2 — share the final build

Collect from the **same formal OFF/ON arms** (no extra GPU cost): loss, grad norm (if native),
learning rate, optimizer step, NaN/Inf, native accuracy/eval metric (if the recipe has one),
final parameter/checkpoint fingerprint where feasible. Compare OFF vs ON, and establish the
**OFF/OFF noise floor**. Do not invent a new accuracy metric for acceptance; do not set tolerance
after the fact.

### Overlap trace (§10, §12)

Separate short fixed-step traces, OFF and ON, using Nsight Systems or an existing trusted GPU
tracer. Compare compute kernels, NCCL, compute/communication overlap, new host/device
synchronization points, timeline gaps. Output: OFF summary, ON summary, delta, new global sync
points. **"No `synchronize` in source" is design evidence only, never acceptance evidence.**
C2 can PASS only if loss/correctness and overlap both show no material regression.

---

## 7. Criterion 3 — real reporting + localisation + latency

Record on real GPU: interval-complete timestamp → collector ingest → window verdict creation →
`report_once` → platform perf export/write. Report completion→ingest, ingest→verdict,
verdict→export, and overall; p50/p95/p99/max.

**Must account for the real wall-clock delay**: the last envelope of a window does not close it;
a verdict may depend on the next envelope crossing `WINDOW_GRACE` or on a flush. Verdict latency is
therefore schedule-dependent. A CPU microsecond benchmark is **not** sufficient.

### C3 verdict rule (§12, §14)

If the maintainer accepts **collector near-real-time + existing platform rollout-cadence export**
as "实时上报", prove with real GPU data that straggler verdicts continuously enter the existing
platform record during training with latency/localisation sufficient to act, and submit the
complete evidence for the maintainer's judgement.

If the requirement is a **near-real-time platform push independent of rollout cadence**, the
current implementation remains **PARTIAL** and an async exporter needs separate approval. Never add
training-thread HTTP to force a PASS. Any async exporter is a product change ⇒ unfreezes `cac4cb6`
and forces C1/C2 re-evaluation.
Shape if ever authorised: collector → bounded queue → dedicated background reporter → existing
MetricsService/platform API, with **0 HTTP / 0 socket wait / 0 blocking queue / 0 new collective**
on the training thread; collector ingest never waits on platform HTTP; platform failure degrades to
drop/counter and cannot affect training.

### Verdict sample to retain (§13)

One real verdict with: rank, raw_stage, coarse_stage, observed_ms, peer reference, relative delta,
absolute gap, workload tokens, coverage, measurement_kind, facts, candidate_causes, persistence,
report timestamp — so a reviewer sees at a glance who is slow, where, by how much, why it was
judged, what is known and what is not.

---

## 8. Attention / MoE scope (§16)

Official scope lists forward/backward, communication, optimizer, attention/MoE. Current state:
the first three are implemented; **attention/MoE are schema-only / unsupported**, and the RFC says
so honestly. Before final acceptance: either the mentor confirms that a reserved-hint capability
suffices for phase one, or real stage instrumentation is added. **Do not self-authorise the
feature expansion.**

---

## 9. Instrumentation to watch during every formal ON arm (§14)

```
envelopes · judged · late · duplicate · invalid
readout_timeout · event pool exhaustion · queue/drop
```

Must continuously hold: **`late ≈ 0`** and **`forward-backward` does not disappear**. If load
introduces readout timeouts, pool exhaustion or head-of-line accumulation, **do not hide it** —
that is exactly the real trade-off of bounded head-of-line waiting introduced by `appendleft`.

**Never revisit the strict late contract** (§15): relaxing the late tolerance is already refuted —
it breaks 7 pre-existing contract tests. If an ordering problem reappears on GPU, first prove the
observer delivery invariant; do not loosen the collector dedup contract.

---

## 10. Delivery-order semantics — exact wording (§4)

Correct: *deferred CUDA intervals are requeued at the head so wire delivery preserves the sequence
stamped at interval completion.* This is **bounded head-of-line waiting, not zero head-of-line
blocking**; `_readout_timeout_s` is the upper bound, and past it the interval is delivered as
`readout_timeout` rather than blocking indefinitely.

Forbidden: "without head-of-line blocking", unless a reorder buffer or equivalent non-blocking
ordered commit is actually implemented.

---

## 11. Public-text hygiene, in parallel with GPU work

Fix: RFC #357 criterion-1 stale duplicate; PR #378 stale `ce9b637` HEAD/verification/checklist;
the 2069/614 vs 2112/631 counter provenance; commit the bilingual docs.

**Provenance, machine-computed** (`counter_provenance_audit.json`, `COUNTER_PROVENANCE_AUDIT.md`):
`envelopes` = packets emitted/received; conservation `judged + late + duplicate + invalid ==
envelopes` holds exactly in every arm.

| arm | envelopes | judged | late | dup | invalid | conserved |
|---|---|---|---|---|---|---|
| abba-cac4cb6-run4/S1-on | 2112 | 2112 | 0 | 0 | 0 | yes |
| abba-ce9b637/S1-on | 2112 | 1481 | 631 | 0 | 0 | yes |
| abba/S1-on (47581e0) | 2112 | 1403 | 709 | 0 | 0 | yes |

`2069/1455/614` is a **periodic snapshot** (`abba-ce9b637/S1-on/job.log:3984`, 10 s before the arm
ended), superseded by the final `2112/1481/631`. `late=614` appearing twice came from a different
arm (`abba/S1-on/job.log:2912`). The `969/969/0` figure was a mid-run read; the final value is
`2112/2112/0`.

Bilingual docs to commit: `docs/en/guide/straggler-profiler.md`,
`docs/zh/guide/straggler-profiler.md`; check EN/ZH parity, real config names, default OFF, metric
semantics, attention/MoE = reserved/unsupported, honest collector/reporting cadence, complete
Known Limits, **no machine paths / IPs / private environment info**; `pre-commit --all-files`;
one docs-only commit:

```
docs(straggler): add profiler user guide and sync acceptance state
```

Then record `PRODUCT_CODE_SHA = cac4cb6`, `PR_HEAD = <docs commit>`. Every formal GPU artifact must
record `PR_HEAD`, `PRODUCT_CODE_SHA` and `git diff PR_HEAD..PRODUCT_CODE_SHA`; if `PR_HEAD` adds
docs only, state plainly that production code = `cac4cb6`. A docs SHA is **not** a new product
freeze and carries no profiler binary semantics.

---

## 12. Final convergence (§18, §19)

Do not keep rewriting the bodies frequently during the campaign — keep facts synchronised, then
converge once at the end. Final RFC = design + contract + official acceptance + known limits.
Final PR = What / Changes / Verification / Risk / Checklist. History (614 late, the refuted
tolerance change, Ray-address attempts, the mis-kills, the RFC 0-byte incident) goes into the
EVIDENCE / FINAL_ACCEPTANCE_REPORT, **not** into the PR body. Target: reviewer understands the
implementation in 5 minutes and the acceptance in 10.

`TASK11_FINAL_ACCEPTANCE_REPORT.md` must contain: PRODUCT_CODE_SHA, FINAL_PR_HEAD, EVIDENCE_SHA,
environment (GPU model, driver, recipe hash, dataset hash); C1 (all pair rows, whole-run,
throughput, mean/median, p50/95/99, startup, steady, CI, verdict); C2 (loss comparison, optimizer
continuity, NaN/Inf, checkpoint/parameter evidence, overlap trace, verdict); C3 (real verdict
example, reporting latency, platform export path, localisation, known cadence limitation,
verdict); plus late/drop conservation, failure isolation, known limits, full test summary and
CI/review state.

---

## 13. Execution order (fused, do not reorder)

```
1  environment snapshot                     [DONE 2026-09-26T16:54:03+08:00]
2  clean Task 11 Ray lifecycle
3  OFF smoke (3-5 steps)
4  ON smoke (3-5 steps)
5  confirm late=0 / forward-backward coverage restored
6  freeze experiment config + hash
7  6-pair AB/BA campaign            (C1, and C2 loss data collected in the same arms)
8  C2 short overlap traces (OFF, ON)
9  C3 real reporting latency + real verdict sample
10 aggregate statistics
11 immutable evidence
12 docs / RFC / PR final sync
13 final review
```

No product-code change anywhere between 3 and 9.

---

## 14. Reporting template (every subsequent round)

```
PRODUCT_CODE_SHA = ; PR_HEAD =
GPU_EXCLUSIVE = YES/NO ; RAY_CLEAN_SMOKE = PASS/FAIL
OFF_SMOKE = ; ON_SMOKE =
VALID_PAIRS = ; INVALID_PAIRS =
C1_WHOLE_RUN = ; C1_THROUGHPUT = ; C1_SESSION_ESTIMATE = ; C1_STARTUP = ; C1_STEADY = ; C1 =
C2_LOSS = ; C2_OVERLAP = ; C2 =
C3_REPORT_LATENCY = ; C3_PLATFORM_PATH = ; C3 =
LATE = ; DROPS = ; FORWARD_BACKWARD_COVERAGE =
TESTS = ; PRE_COMMIT =
CODE_BLOCKERS = ; ACCEPTANCE_BLOCKERS = ; DOC_BLOCKERS = ; INFRA_BLOCKERS =
READY_FOR_REREVIEW = YES/NO
```