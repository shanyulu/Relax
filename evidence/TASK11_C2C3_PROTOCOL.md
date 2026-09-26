# Task 11 — C2/C3 pre-registered execution protocol (build `cac4cb6`)

Status: **pre-registered, no results.** This document fixes *what will be measured, where it is
read from, and every tolerance* before any C2/C3 data is seen. It is written to be executed
verbatim; any deviation is a new protocol and must be reported as one.

## 0. Frozen build and preconditions

- Frozen revision: `cac4cb6447154e6ae4f563eabab7fecf43dba790` (branch
  `feat/task11-straggler-profiler`), `git.dirty=false`, as recorded in every campaign
  `manifest.json` under `git.commit` / `git.tree_label`.
- Profiler source is pinned by `manifest.json` `straggler_sha256_at_start`; re-verify it
  equals `provenance.worktree_straggler_sha256` before and after each arm.
- Formal arms only. The only difference between arms is `RELAX_STRAGGLER_ENABLE`;
  everything else (recipe `scripts/training/sft/run-qwen3-0.6B-4xgpu-dp4-observer.sh`,
  4 GPUs, dataset `dataset_sha256`, seed, step count, wrapper) is identical across arms.
- ON-arm profiler settings are the ones recorded in `manifest.json` `relax_env` (window 5 s,
  persist 3 windows, report interval 10 s, warmup 2 windows). C2/C3 runs must not change them.
- Between arms: previous training process exited, Serve application cleaned, VRAM released,
  no residual collector/observer, Ray healthy. A single long-lived process flipping an env
  var is **not** an independent arm.
- Statistical unit is the **pair/session**, never the optimizer step.
- **All tolerances below are frozen at the moment this file is committed.** No tolerance may
  be chosen, widened, or narrowed after seeing C2/C3 data. If a tolerance turns out to be
  wrong, that is a new pre-registration, recorded as such, and the old result stands.

## 1. Criterion 2 — loss / correctness and GPU overlap

### 1a. Loss and correctness comparison (same formal OFF/ON arms, no extra GPU cost)

Capture per arm, from the arm's `job.log` and `summary.json` (names recorded from the log
itself, never assumed — the recipe's actual keys are read first):

| item | exact source | per-step or final |
| --- | --- | --- |
| training loss (native key, e.g. `train/loss` if the recipe emits it) | `job.log` metric dict / `summary.json` `train_metrics` | per step |
| gradient norm (only if the recipe emits one natively) | same | per step |
| learning rate | same | per step |
| optimizer step ordinal | `summary.json` `observation.collector_status.training_context.step_ordinal`, `job.log` `perf <n>:` labels | final |
| NaN / Inf counts in loss and grad norm | derived count over the per-step series | final |
| native accuracy / eval metric (only if the recipe has one) | `job.log` / `summary.json` | as emitted |
| final parameter / checkpoint fingerprint | sha256 over the final checkpoint files under the arm's checkpoint dir | final |
| wall clock, throughput, step count | `manifest.json` `wall_seconds`, `summary.json` `perf_metrics` | final |

Comparison is OFF vs ON, **paired by step index**, plus the **OFF/OFF noise floor** from two
OFF arms measured with the same estimator (never a single OFF sample).

Pre-registered tolerance (frozen now):

1. No NaN/Inf in either arm. Any NaN/Inf is a C2 failure.
2. Loss: the OFF→ON per-step delta must lie inside the OFF/OFF noise band — defined as the
   full range `[min, max]` of the per-step paired delta measured between the two OFF arms,
   with a floor of `±0.5 %` of the OFF mean when the OFF/OFF range is narrower than that.
3. Final fingerprint: equal under a fixed seed, or a recorded, explained nondeterminism
   source with both fingerprints and the differing tensors listed. An unexplained mismatch
   is a C2 failure.
4. C2 loss/correctness can PASS only if (1)–(3) hold on **≥2 independent pairs**; one pair is
   a point estimate and must be reported as such.

### 1b. GPU overlap trace (short, fixed-step Nsight Systems, OFF and ON)

- Identical short run per arm: same recipe, same 4 GPUs, same fixed small step count
  (fixed before the run, recorded in the C2 manifest), only `RELAX_STRAGGLER_ENABLE` differs.
- Command shape: `nsys profile --trace=cuda,nvtx,osrt,cublas,cudnn --sample=none --cpuctxsw=none`
  around the training process, one `.nsys-rep` per arm, both opened with the same options.
- Capture from each trace: kernel table (per-kernel total time, count), NCCL kernel time and
  share, compute vs communication overlap percentage, number and kind of host/device
  synchronizations (`cudaStreamSynchronize`, `cudaDeviceSynchronize`, blocking D2H copies),
  timeline gaps above the fixed gap threshold, NVTX ranges for the profiler's own work.
- Output: OFF summary, ON summary, delta, and the explicit list of **new** global sync points.
- Pre-registered tolerance (frozen now): overlap percentage must not drop by more than
  `1.0` percentage point, NCCL kernel time must not increase by more than `1.0 %`, total
  kernel time must not increase by more than `0.5 %`, and there must be **zero new**
  `cudaDeviceSynchronize` / blocking-D2H sites on the training path. The short trace is
  supporting evidence for the mechanism; the paired step-time campaign remains the cost
  evidence, and "no `synchronize` in source" is design evidence only, never acceptance
  evidence.
- C2 PASS requires **both** 1a and 1b.

## 2. Criterion 3 — real reporting latency and one full real verdict sample

### 2a. Reporting latency

The frozen JSONL schema records `host_start` / `host_end` on envelopes and durations
(`rank_host_ms`, `reference_host_ms`) on verdicts, but **no ingest, verdict-creation, or
persist timestamps**. C3 therefore has two acceptable measurement paths; at least one is
required, and the chosen one is recorded before the run:

- **Path A (instrumentation, preferred):** add host-monotonic stamps and surface them on the
  persisted rows:
  - `ingest_host_s` — stamped when the receiver accepts a packet (envelope row);
  - `verdict_host_s` — stamped when the detector emits a verdict (verdict row);
  - `persist_host_s` — stamped when the row is flushed (envelope and verdict rows).
- **Path B (external tracer, only if Path A is impossible):** timestamp packet receive,
  verdict emission, and file write externally, keyed to the same `run_id` + `rank` +
  `window_index` + stage so rows can be joined. Path B must still produce per-record
  timestamps; whole-file mtime is **not** acceptable.

Both paths use the same host monotonic clock as `host_start`/`host_end`, so hops are
comparable. The chain measured is:

`interval complete (envelope host_end) → collector ingest → verdict creation → persisted line`

Report per hop and overall: `n`, `p50`, `p95`, `p99`, `max`, in milliseconds.

Separately and always, report the **schedule-dependent delay**: a window's last envelope
does not close the window, so the gap `derived_window_close(window_index) − host_end(trigger
envelope)` is reported on its own and is **not** charged against the processing-latency
budget (it is window-schedule-bound, not work the profiler does). The window close is
derived from the cohort anchor (earliest envelope `host_start`) plus `window_index`, using
the window length recorded in `manifest.json`.

Pre-registered latency budget (frozen now):

- `p99(collector ingest) < 5 ms`
- `p99(verdict creation) < 20 ms`
- `p99(persisted line) < 5 ms`
- `p99(overall interval complete → persisted line) < 30 ms`
- `max(overall) < 100 ms`
- schedule-dependent delay is reported with `p50/p95/p99/max` and is bounded by the window
  length by construction; it is **not** subject to the numbers above.

C3 latency PASS requires ≥2 pairs and every budget above met on the pair-level aggregate;
any missing timestamp means the hop is reported as absent and C3 latency is **not** PASS.

### 2b. One full real verdict sample

Archive exactly one verdict row, copied verbatim from the ON arm's
`straggler_verdicts.jsonl` at this build (never hand-typed), together with the raw JSONL line
and the file path + line number. The archived sample must expose, by name, all of:

| required field | frozen-schema source |
| --- | --- |
| `rank` | `verdict.rank` |
| `raw_stage` | `verdict.name` (stage as emitted) |
| `coarse_stage` | coarsened stage label — record the coarsening used; if the frozen schema has no such field, record it as `absent` and say which field would carry it |
| `observed_ms` | `verdict.facts.observed_ms` |
| peer reference | `verdict.facts.peer_fastest_ms` and `verdict.facts.peer_median_ms`, stating which one drove the decision (`facts.ratio` uses the fastest peer) |
| relative delta | `verdict.deviation` / `verdict.facts.ratio` |
| absolute gap | `verdict.facts.absolute_delta_ms` |
| workload tokens | `verdict.facts.workload_rank_tokens` and `verdict.facts.workload_peer_tokens` (plus `tokens_delta`) |
| coverage | `verdict.facts.coverage_ratio`, `verdict.facts.cohort_size`, `verdict.facts.cohort_expected` |
| `measurement_kind` | `verdict.measurement_kind` |
| `facts` | `verdict.facts` (entire dict, verbatim) |
| `candidate_causes` | `verdict.candidate_causes` (verbatim) |
| persistence | `verdict.consecutive_windows` and `verdict.facts.persistence` |
| report timestamp | **must be added by Path A/2a** (`verdict_host_s` and `persist_host_s`); absent in the frozen schema |

The sample must also state: `kind` (verdict kind), `reason`, `cohort`, `window_index`,
`label`, `host_only`, and the collector counters that produced the window (from the periodic
`straggler[...]` line and final `collector_status`).

## 3. Tolerance freeze record

| tolerance | value | unit | fixed by |
| --- | --- | --- | --- |
| C2 loss deltas | inside OFF/OFF band, floor `±0.5` | % of OFF mean | this document, before C2 data |
| C2 fingerprints | equal under fixed seed, or explained | — | this document |
| C2 overlap drop | `≤ 1.0` | percentage point | this document |
| C2 NCCL time growth | `≤ 1.0` | % | this document |
| C2 total kernel time growth | `≤ 0.5` | % | this document |
| C2 new global sync sites | `0` | count | this document |
| C3 ingest p99 | `< 5` | ms | this document |
| C3 verdict p99 | `< 20` | ms | this document |
| C3 persist p99 | `< 5` | ms | this document |
| C3 overall p99 | `< 30` | ms | this document |
| C3 overall max | `< 100` | ms | this document |
| C1 whole-run overhead | `< 0.5` | % | official criterion, unchanged |

These values are fixed **before the data exists**. They may not be edited after a C2/C3 run;
a later change is a new pre-registration and the earlier run keeps its original verdict.

## 4. Anti-patterns explicitly forbidden

- Treating optimizer steps as independent samples, or reporting a step-level confidence
  interval as if it were session-level.
- Announcing C1/C2/C3 PASS on a median or steady-state number alone.
- Substituting a proxy (file mtime, log line order, packet `seq`) for a missing timestamp and
  presenting it as a measured latency hop.
- Overwriting the first valid failed short run with a longer confirmatory run; the long run is
  additional explanation only.
- Setting or moving any tolerance after seeing the result.