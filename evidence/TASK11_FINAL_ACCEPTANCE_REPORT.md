# Task 11 — Final Acceptance Report (straggler profiler / RFC #357 / PR #378)

Prepared from sources actually read at report time. Every figure below is copied
from a cited source path or from a command whose output is quoted. Nothing is
invented, extrapolated or rounded into a claim. The two long bodies (sections 18
and 19) are reproduced verbatim from the live public GitHub objects.

Provenance of the live bodies: `gh issue view 357 --repo redai-studio/Relax
--json body,updatedAt -q .` and `gh pr view 378 --repo redai-studio/Relax --json
body,headRefOid,updatedAt -q .` both succeeded; no TLS retry was needed.

---

## FINAL_CODE_FREEZE_SHA

The only SHA I read that is explicitly documented as a **code freeze** is
`ce9b637635220e218225f3b001898334754cec14`.

- Source: RFC #357 live body (`gh issue view 357`), *Evidence* section —
  "Frozen state: code-freeze SHA `ce9b637635220e218225f3b001898334754cec14`,
  working tree clean, pre-commit green on the changed file set."
- Source: `gpu_campaign/abba-ce9b637/S1-off/manifest.json` and
  `.../S1-on/manifest.json`, `git.commit` = `ce9b637635220e218225f3b001898334754cec14`,
  `tree_label` = `CLEAN@ce9b63763522`, `dirty` = `false`.

The **current tip is one commit ahead and is not covered by any freeze record I
could read**:

- `cd /root/autodl-tmp/relax-work/task11-c2 && git rev-parse HEAD` →
  `cac4cb6447154e6ae4f563eabab7fecf43dba790`.
- `git log --oneline -3` →
  `cac4cb6 fix(straggler): keep retried intervals in delivery order`,
  `ce9b637 style(straggler): apply ruff and docformatter to the audited files`,
  `d3ca9e3 style(straggler): apply ruff format to the reporter tests`.
- The freeze mechanism on this branch is the per-arm `manifest.json`
  (`git.commit` + `tree_label`). The live campaign arm
  `gpu_campaign/abba-cac4cb6/S1-off/` contains **`job.log` only** — no
  `manifest.json` — so `cac4cb6` has no recorded freeze.

**FINAL_CODE_FREEZE_SHA = `ce9b637635220e218225f3b001898334754cec14`** (last
recorded code freeze; the operative tip `cac4cb6447154e6ae4f563eabab7fecf43dba790`
is a post-freeze fix with no freeze record).

## FINAL_PR_SHA

`cac4cb6447154e6ae4f563eabab7fecf43dba790`.

- Source: `gh pr view 378 --repo redai-studio/Relax --json body,headRefOid,updatedAt -q .`
  → `"headRefOid":"cac4cb6447154e6ae4f563eabab7fecf43dba790"`,
  `"updatedAt":"2026-09-26T04:01:00Z"`.
- PR #378, `headRefName` = `feat/task11-straggler-profiler`, base `main`
  (`gh pr view 378 --json state,isDraft,...`).
- The **PR body text itself is stale**: it still says "current head is
  `ce9b637`" and that the readout-order fix was reverted, while the public
  `headRefOid` is already `cac4cb6` (section 18/19 quote the stale body verbatim;
  section 20 records that no comment corrects it).

## EVIDENCE_SHA

There is no single verifiable EVIDENCE_SHA for the acceptance evidence, and I
will not invent one:

- The acceptance evidence root `/root/autodl-tmp/relax-work/task11_evidence/`
  is **not a git repository**: `git rev-parse --show-toplevel` →
  `fatal: not a git repository (or any parent up to mount point /root)`.
- The task 11 evidence/demo branch I can read is
  `contrib/task11-straggler-analysis` @
  `74de1317a5eb9be411a1d730e48bb01d0ff56054` (local ref, mirroring
  `remotes/shanyulu/contrib/task11-straggler-analysis`; commit message
  `docs(task11): record the pooled-statistics revision in RFC and evidence`,
  2026-09-25 01:18:43 +0800). `EVIDENCE.md` names this branch as the evidence
  root for the standalone prototype (`EVIDENCE.md` §0 and §6), not for the
  in-workspace acceptance artefacts.
- Frozen estimator artefact: `c2_phase3_estimator_freeze.json` records
  `"sha256": "2d93332c9c59f68c8f4be7ac3add0386499fc8a8d26e45d48261d46dfa6102d5"`
  for `analyze_overhead.py`; `sha256sum analyze_overhead.py` reproduces exactly
  that hash, and the file records `"frozen_utc": "2026-09-25T11:12:06Z"`,
  `"frozen_before_any_arm": true`, `"runs_observed_at_freeze": 0`.
- Per-arm content hash: `straggler_sha256_at_start` =
  `bdc691059efcb717c8ec0ff5fe9569469924b69a67caec960e764bc1144f915f` in
  `gpu_campaign/abba-ce9b637/{S1-off,S1-on}/manifest.json` and in the
  `provenance` block of each `manifest.json`.

**EVIDENCE_SHA = unrecorded for the acceptance workspace** (not a git repo);
nearest immutable evidence reference:
`contrib/task11-straggler-analysis @ 74de1317a5eb9be411a1d730e48bb01d0ff56054`.

## Public GitHub SHA consistency

| item | value | source |
| --- | --- | --- |
| PUBLIC_HEAD (`gh pr view 378` `headRefOid`) | `cac4cb6447154e6ae4f563eabab7fecf43dba790` | `gh pr view 378 --json body,headRefOid,updatedAt -q .` |
| LOCAL_HEAD (`git rev-parse HEAD`) | `cac4cb6447154e6ae4f563eabab7fecf43dba790` | `cd /root/autodl-tmp/relax-work/task11-c2 && git rev-parse HEAD` |
| HEAD_MATCH | **YES** | equality of the two values above |
| working tree at first read (≈12:04) | clean — `git status --porcelain` printed nothing | `git status --porcelain` |
| working tree at report time (12:12:44) | **dirty** — `M docs/.vitepress/config.mts`, `?? docs/en/guide/straggler-profiler.md`, `?? docs/zh/guide/straggler-profiler.md` | `git status --porcelain`; `stat -c '%y %n'` |
| branch | `feat/task11-straggler-profiler` | `git rev-parse --abbrev-ref HEAD` |

The public **head object and the local checkout agree exactly**. What does *not*
agree is the public **prose**: the RFC #357 body (`updatedAt`
`2026-09-26T03:54:20Z`) and the PR #378 body (`updatedAt` `2026-09-26T04:01:00Z`)
both still name `ce9b637` as the freeze/head, and the PR body still states the
readout-order fix "was therefore reverted and the tree is back at `ce9b637`",
whereas the pushed head is `cac4cb6 fix(straggler): keep retried intervals in
delivery order`. So: **head SHA match = YES; documented-freeze/head consistency =
NO, stale by one commit.**

**Tree-state honesty.** The working tree was clean when first read and became
dirty during this session. The changes are `docs/.vitepress/config.mts`
(modified, mtime 2026-09-26 12:09:46) plus two untracked files
`docs/en/guide/straggler-profiler.md` and `docs/zh/guide/straggler-profiler.md`
(mtime 2026-09-26 12:11:37). **I did not create or modify any of them** — this
report's only write was `task11_evidence/TASK11_FINAL_ACCEPTANCE_REPORT.md`
(mtime 12:11:52). They are concurrent-agent activity in the shared worktree of
the kind the RFC/PR bodies already record. Consequence: the documented freeze
condition ("working tree clean") holds at HEAD `cac4cb6` only for the code
tree as read, **not** for the tree at report time.

## Official criterion 1 result

Criterion: "整体性能开销低于 0.5%" (overall overhead below 0.5 %).

**Result: PARTIAL.**

Campaign accounting, using the completion rule required for this report (an arm
counts only with **both** a `job.log` carrying 48 `perf <n>: {` lines **and** a
`manifest.json`):

| campaign | arm dirs | completed arms | paired sessions |
| --- | --- | --- | --- |
| `gpu_campaign/abba-cac4cb6/` (live, frozen tip `cac4cb6`) | 1 (`S1-off`) | **0** (`S1-off` has no `manifest.json` and only 3 `perf <n>: {` lines; its `job.log` shows Ray startup failures, e.g. `ValueError: Invalid Ray address: 'http://127.0.0.1:8265'`) | 0 |
| `gpu_campaign/abba-ce9b637/` (archived, `ce9b637`) | 3 (`S1-off`, `S1-on`, `S2-on`) | 2 (`S1-off` and `S1-on`: each has `manifest.json` + 48 perf lines) | 1 (`S1`) |
| `gpu_campaign/abba/` (archived, `47581e0`) | 4 (`S1-off`, `S1-on`, `S1-on.attempt1-killed-by-operator`, `S2-on`) | 2 (`S1-off`, `S1-on`) | 1 (`S1`) |

The preregistered estimator requires **≥6 fresh-process paired AB/BA sessions**
(`TASK11_ACCEPTANCE_PROTOCOL.md` §7, "Real recipe AB/BA <0.5% | ≥6 fresh-process
paired AB/BA sessions through the frozen estimator"). Only **2 paired sessions
exist in total, and 0 on the frozen tip**. The single-session and microbenchmark
numbers are supporting evidence only.

Decision rule actually frozen before any arm
(`c2_phase3_estimator_freeze.json`): *"overhead < 0.5% only if median AND mean
95% upper bounds < +0.005, AND whole-run wall median delta < +0.005, AND
steady-state p50 median delta < +0.005"* (`analyze_overhead.py`
`ACCEPTANCE_BOUND = 0.005`). No session-boostrapped interval is computable from
2 sessions (and none from the live campaign at all).

**Verdict: PARTIAL — the single concrete missing measurement is the ≥6 completed
fresh paired AB/BA sessions on the frozen tip; the live campaign
`abba-cac4cb6` has 0 of the required arms complete (1 arm dir, no
`manifest.json`, 3 of 48 perf lines).**

## Official criterion 2 result

Criterion: "端到端跑通，不影响训练精度、loss 指标和已有通算 overlap 等加速收益."

**Result: PARTIAL.**

What I read that supports the mechanism (design evidence, **not** acceptance
evidence):

- Default-off: with `RELAX_STRAGGLER_ENABLE` unset `get_straggler_timers()`
  returns `None` and `config.timers` stays upstream (RFC #357 *Design
  invariants*).
- No training-path collective; the observer is failure-isolated and bounded with
  counted drops (RFC #357 *Design invariants* / *Failure model*, pinned by the
  AST/source guard and the runtime instrumentation test).

What is missing, and why this is not a pass:

- **No loss / grad-norm / accuracy measurement exists.** Every arm summary I
  read carries an empty `train_metrics` object — e.g.
  `gpu_campaign/abba-ce9b637/S1-off/summary.json` and
  `.../S1-on/summary.json` both end with `"train_metrics": {}` (the parser
  `analyze_run.py` `parse_steps()` found no `step <n>: {...}` lines in the
  logs). The RFC body states the same: "No loss or overlap evidence exists".
- **No compute/communication overlap trace exists** on the shipping build.

**Verdict: PARTIAL — the single concrete missing measurement is a paired
ON/OFF loss + grad-norm equivalence comparison (same seed/data, within the
run's own seed-to-seed spread) plus a short `torch.profiler`
compute/communication overlap trace on the frozen tip.**

## Official criterion 3 result

Criterion: "结合现有平台能力实时上报，结果清晰、便于定位问题."

**Result: PARTIAL.**

What I read that supports the mechanism:

- Reporting is an adapter: `report_once` returns `perf/straggler/*` scalars and
  `log_perf_data_raw` merges them with `log_dict.update(...)` into the
  already-made perf dict before the single existing platform write; no new HTTP
  request and no new collective (RFC #357 *Official acceptance*, criterion 3).
- Localisation carries the raw `stage` plus `facts` / `candidate_causes` with
  default `undetermined`, and distinguishes `host_only_stall` /
  `gpu_stream_stall` / `attribution_unknown`.
- Live hardware confirms coarse-stage presentation: verdicts such as
  `straggler stage: name=params-all-gather coarse_stage=communication`
  (RFC #357 *REAL-GPU CORRECTION*).
- A real collector status file exists for the ON arm:
  `gpu_campaign/abba-ce9b637/S1-on/run_10000000/collector_status_rank0_tp0_pp0_vpp-1_cp0_ep0_dp0_chunk-1.json`
  (plus `.../runtime_status*.json`), with `envelopes=2112`,
  `verdicts=540`, `late_packets=631`.

What is missing / bounding the claim:

- **No real-GPU reporting latency exists.** The only hop latencies are
  in-process CPU proxies with a fake device backend (section 11), and the
  RFC/PR body says exactly that.
- Export is at **rollout cadence**, on the training thread, primary rank only;
  the collector's summary and status JSON are log/file evidence, not platform
  metrics.
- Under `pp_size > 1` the collector-versus-export rank mismatch stands (marked
  by `collector_status_available=0`, not fixed).

**Verdict: PARTIAL — the single concrete missing measurement is a real-GPU
sample→platform-visible reporting latency from a real ON run (non-zero
`perf/straggler/*` telemetry plus measured timestamps), which does not exist
yet.**

## Overhead table

### Live campaign (frozen tip `cac4cb6`) — cannot be computed

`gpu_campaign/abba-cac4cb6/` contains one arm directory, `S1-off/`, with
`job.log` only (no `manifest.json`, no `summary.json`) and 3 of the 48
`perf <n>: {` lines; the log records Ray init failures. **No paired session has
completed in the live campaign, so no overhead number can be computed from it.**

### Most recent completed paired session on the feature code (`ce9b637`)

`gpu_campaign/abba-ce9b637/S1-off/job.log` vs `.../S1-on/job.log`; identical
commit (`ce9b637635220e218225f3b001898334754cec14`, `dirty=false`), identical
recipe (`scripts/training/sft/run-qwen3-0.6B-4xgpu-dp4-observer.sh`), identical
dataset (`dataset_sha256` `44f9ddacd1e078d60d1a65d43dda76283b5ba68c6db7bbd54462126cd6a59428`),
48 optimizer steps per arm, only `RELAX_STRAGGLER_ENABLE` differs
(`manifest.json` `relax_env`; OFF arm `relax_env={}`, ON arm
`RELAX_STRAGGLER_ENABLE=1` + collector address). Series parsed from the two
`job.log` files with the regex `'perf/train_time': <float>` and
`'perf/actor_train_time': <float>`, 48 values each.

| metric | OFF median (s) | ON median (s) | paired median delta | paired mean delta | max abs delta (s) | N sessions |
| --- | --- | --- | --- | --- | --- | --- |
| `perf/train_time` | 15.857195615768433 | 15.875278353691101 | −0.028449 % | −1.401510 % | 4.831151 | 1 |
| `perf/actor_train_time` | 10.824964165687561 | 10.844772696495056 | −0.048206 % | −2.007885 % | 4.842192 | 1 |

Definitions, stated because the published text mixes them: **paired median
delta** = median over the 48 per-step relative deltas `(ON_i − OFF_i)/OFF_i`;
**paired mean delta** = `(mean(ON) − mean(OFF))/mean(OFF)` — this second
definition is the one that reproduces the published `−1.402 %` and `−2.008 %`,
and the paired-median definition reproduces the published `−0.028 %` and
`−0.048 %` in the RFC/PR body. For full transparency I also computed the
alternatives: mean of per-step relative deltas = −1.345015 % (`train_time`) and
−1.847076 % (`actor_train_time`); delta of medians = +0.114035 % and
+0.182989 %. The median and the mean disagree in sign/direction, which is
exactly why the frozen rule requires **both** interval upper bounds below
+0.5 % and additional wall/p50 checks.

### Older archived pair (`47581e0`) — not comparable

`gpu_campaign/abba/S1-off/manifest.json` and `.../S1-on/manifest.json` record
`git.commit = 47581e06a1a0166251d4148204ffaf4cb529fd6a`, a **different
revision** from the frozen tip. Computed from those two `job.log` files:
`perf/train_time` OFF median 0.750199556350708 s, ON median 0.7489798069000244 s,
paired median delta +0.403182 %, paired mean delta +3.368289 %, max abs delta
2.596636 s, N = 1. `perf/actor_train_time` OFF median 0.7237231731414795 s, ON
median 0.7260816097259521 s, paired median delta +0.469636 %, paired mean delta
+0.456152 %, max abs delta 2.601977 s, N = 1. These are the numbers behind the
"single-session point estimate" quoted in the RFC/PR body
(`step_time` median −0.118 %, mean +2.558 %); they measure different code.

### Mandatory caveats

- **All of this was measured under machine load.** The RFC #357 and PR #378
  bodies state the pair "ran under a machine load near 50 with about 35 s per
  step against 6.5 s per step in the archived arms". The manifests themselves
  carry no load field (`gpu_before`/`gpu_after` show only 1 MiB memory and 0 %
  utilisation, i.e. idle at the sampling instants), so the load figure is
  quoted from the bodies, not re-measured here.
- **The archived arms and the current arms are not comparable.** Whole-run wall
  clock per optimizer step: archived `abba/S1-off` =
  `wall_seconds` 310.979 / 48 ≈ **6.48 s/step**; current `abba-ce9b637/S1-off` =
  `wall_seconds` 1555.467 / 48 ≈ **32.41 s/step** (both `manifest.json`,
  `exit_code` 0). The live campaign is even slower still. A cross-campaign
  comparison is therefore invalid, and no pooled overhead figure is offered.
- These are **point statistics from N = 1 session**, not the preregistered
  session-bootstrapped interval; they cannot decide criterion 1.

## Loss / correctness table

**Not run.** No loss, grad-norm, or correctness-gate measurement exists: every
arm summary read (`gpu_campaign/abba-ce9b637/{S1-off,S1-on}/summary.json`,
`gpu_campaign/abba/{S1-off,S1-on}/summary.json`) carries `"train_metrics": {}`
and `analyze_run.py` `parse_steps()` extracted nothing. The exact run that would
fill this section is the protocol's H2 clean paired ON/OFF recipe run at the
frozen tip with per-step loss and grad-norm sequences compared within the run's
own seed-to-seed spread (`TASK11_ACCEPTANCE_PROTOCOL.md` §H2), i.e.
`NUM_ROLLOUT=48` ON and OFF on `scripts/training/sft/run-qwen3-0.6B-4xgpu-dp4-observer.sh`
at the same seed and dataset, plus the `off`-vs-`off` null control.

## Overlap trace result

**Not run.** No `torch.profiler` compute/communication overlap trace exists for
either arm. The exact run that would fill this section is staged block 7 of
`GPU_CAMPAIGN_STAGED.md`: one ON + one OFF `torch.profiler` recipe run on the
frozen tip, comparing the overlap of compute and communication kernels between
the two arms.

## Reporting latency table

Source: `/tmp/straggler_latency_results.json` (`timestamp`
`2026-09-26T10:52:06+0800`; environment block: Python
3.12.3, Xeon Platinum 8352V, 128 CPUs, torch 2.11.0+cu130,
`thread_switch_interval_s` 0.005, `worktree`
`/root/autodl-tmp/relax-work/task11-c2`). **All values are CPU proxies measured
with a fake device backend; there is no real-GPU reporting latency yet.** The
fake-device rows are labelled as such and must not be read as device latency.
Iteration counts in the file: `train` 20000, `delivery` 20000, `verdict` 4000,
`report` 20000.

| path | variant | n | p50 (µs) | p95 (µs) | p99 (µs) | max (µs) |
| --- | --- | --- | --- | --- | --- | --- |
| completion → ingest (host-only) | `tight_batch256` | 20000 | 20.260 | 22.976 | 35.485 | 976.676 |
| completion → ingest (host-only) | `paced_batch8` | 20000 | 20.863 | 23.261 | 36.955 | 845.078 |
| completion → ingest (host-only) | `yield_each_sleep0` | 20000 | 64.697 | 99.327 | 159.552 | 2486.624 |
| completion → ingest (fake device backend) | `tight_batch256` | 20000 | 6002.450 | 9617.543 | 12598.066 | 22115.363 |
| completion → ingest (fake device backend) | `paced_batch8` | 20000 | 208.406 | 404.978 | 700.066 | 1974.702 |
| completion → ingest (fake device backend) | `yield_each_sleep0` | 20000 | 52.877 | 110.649 | 149.325 | 2375.297 |
| last envelope → verdict (`triggered_close`) | — | 4000 | 52.096 | 70.281 | 87.744 | 342.233 |
| last envelope → verdict (`flush_forced_close`) | — | 4000 | 36.729 | 49.056 | 64.760 | 219.936 |
| `report_once` | populated | 20000 | 34.494 | 35.351 | 86.177 | 724.386 |
| `report_once` | empty | 20000 | 24.725 | 25.565 | 30.084 | 173.407 |
| `report_once` | populated, root logger INFO | 3000 | 83.456 | 85.663 | 200.087 | 1170.697 |
| `report_once` | disabled | 20000 | 0.753 | 0.766 | 0.775 | 79.578 |
| start/stop pair | host-only, no-op consumer (enabled p50 8.294 vs control p50 0.423) | 20000 | Δ +7.873 | Δ +8.440 | Δ +18.390 | Δ +585.342 |
| start/stop pair | host-only, inline local collector ingest (enabled p50 23.996 vs control p50 0.535) | 20000 | Δ +23.443 | Δ +26.138 | Δ +51.713 | Δ +1130.976 |
| start/stop pair | host-only, sender consumer (enabled p50 17.406 vs control p50 0.440) | 20000 | Δ +16.946 | Δ +18.366 | Δ +34.964 | Δ +1084.514 |
| start/stop pair | fake device backend, paced8 (enabled p50 16.153 vs control p50 1.820) | 20000 | Δ +14.320 | Δ +18.876 | Δ +25.159 | Δ +1299.452 |
| `perf_counter_pair_floor` | clock measurement floor | 20000 | 0.108 | 0.162 | 0.166 | 5.072 |

Structural result from the same file: `verdicts_on_last_window_envelope_first_iter`
= **0** out of `verdicts_for_window_on_trigger_first_iter` = 1 across
`triggered_close`, with `iters_with_zero_window0_verdict` = 0 — i.e. ingesting a
window's last envelope produced no verdict in 4000/4000 iterations; a verdict
needs a later envelope beyond `WINDOW_GRACE` or a `flush()`. Also recorded:
`enabled_populated` `metric_keys_last_call` = 10 vs `disabled`
`metric_keys_last_call` = 0, and the `probe_runtime_none_branch`
`public_state_can_reach` = **false** (the "enabled but no runtime" branch is
unreachable through the public API — see section 15).

**No real-GPU reporting latency exists yet.** These numbers bound in-process
Python cost with a fake CUDA-event backend under a manual clock; they are not a
GPU measurement and are not platform-visible latency.

## Sensitivity result

**Not run.** No injected-slowdown sensitivity characterisation exists (no
+5/+10/+20/+50/+100 % TPR/FPR table). The exact run that would fill this
section is staged block 6 of `GPU_CAMPAIGN_STAGED.md`: the injected SM-carve-out
recipe at +5 %, +10 %, +20 %, +50 % and +100 % on the frozen tip, reporting
true-positive and false-positive rates against the persistence threshold.

## Topology result

**Not run.** No TP2×DP2 (or PP2×DP2) cohort-correctness run exists. The exact
runs that would fill this section are staged blocks 4 and 5 of
`GPU_CAMPAIGN_STAGED.md`: one `run-qwen3-0.6B-4xgpu-tp2dp2-observer.sh` run
(topology-equivalent cohort correctness) and, optionally,
`run-qwen3-0.6B-4xgpu-pp2dp2-observer.sh` (proving no cross-stage comparison and
exercising the known collector-versus-export rank mismatch under `pp_size > 1`).

## Fault-isolation result

**Not run** as acceptance evidence. No GPU fault-isolation campaign (staged
blocks A–E, `GPU_CAMPAIGN_STAGED.md` block 3: `gpu_campaign/downgrade_harness.py`
plus a real job) has been executed. `EVIDENCE.md` §1 lists a
CPU/multi-process downgrade harness (`task11_evidence/downgrade_harness.py` +
`downgrade/downgrade_report.json`, collector killed mid-run) as *Validated
(CPU/multi-process)* mechanism evidence, and explicitly says the GPU-touching
re-run "stays Pending acceptance so it cannot contend with other GPU work" —
that is supporting evidence, not an acceptance result. The exact run that would
fill this section is staged block 3: the A–E fault-injection campaign
(`downgrade_harness.py` + a real job) on the frozen tip, asserting that no
failure escapes into `train` / `train_one_step` / the optimizer and that drops
are counted.

## Current known limits

Reproduced from the RFC #357 and PR #378 live bodies, plus the limits they
record. Each is an explicit tracked limitation, not vague future work.

1. **Observer restart / dedup `_newest` contract (E2).** The dedup tracker's
   `_seen` map has a TTL, but its `_newest` map is evicted only by entry count
   and never by time; under a stable `run_id`, a restarted rank whose sequence
   restarts at 1 has every low sequence compared against the retained
   high-water mark and returns `late` until the cap evicts that rank key. NOT
   FIXED.
2. **`peer_median_ms` includes the rank itself (E5).** The published timing
   `peer_median_ms` is a median over all ranks of the pair including the rank
   being judged; the workload gate correctly excludes self and detection uses
   the minimum, so this mislabels evidence without changing a verdict. NOT
   FIXED.
3. **Absolute-floor systematic false negative (E6).** A stage is judged only
   when the gap exceeds **both** 5 % of the fastest peer **and** `min_stage_ms`
   5 ms, so the relative tolerance only binds above ~100 ms and a 10× slowdown
   on a 0.4 ms stage is invisible; a 10× slowdown on a 2.9 ms stage is
   `uncertain`/`below_absolute_floor`, never `straggler`. Documented tradeoff;
   NOT FIXED.
4. **`cohort_below_min_size` unreachable at the default (E7).** Config clamps
   `min_cohort_size` to a floor of 2 and the `cohort_size < 2` case returns
   earlier, so the `cohort_size < min_cohort_size` branch is dead at the
   default; meaningful only when `min_cohort_size >= 3`. The guard was kept, not
   removed. NOT FIXED.
5. **Packets delayed past the window grace are lost (E9).** `WINDOW_GRACE` is 1
   window (default 5 s) while the observer's readout timeout is 30 s; such a
   packet recreates its old window, which is immediately closed as too old and
   judged with a single rank, counted `incomplete` instead of compared. NOT
   FIXED.
6. **Workload stamp taken after the interval closed (E11).** The envelope's
   workload is read when the envelope is built, on the readout thread, after the
   interval completed, so it can belong to a later rollout or step than the
   interval it rides; the envelope's only temporal anchor for the interval is
   `host_start`, and the workload stamp is advisory. NOT FIXED.
7. **`protocol.validate()` never inspects `host_start` (S3).** A finite
   far-future `host_start` is accepted; because the detector closes the oldest
   window once `newest - oldest > WINDOW_GRACE + 1`, one such sample can flush
   every pending window early. NOT FIXED.
8. **No-CUDA path judges on the training thread (E12).** Without device timing
   (or when an interval has no event pair) the observer delivers the envelope
   synchronously on the training thread, so a rank-local or rank-0 collector
   runs `detector.observe` there; `ingest` also calls the periodic-summary path
   while holding the collector's state lock, so that log line is emitted under
   the lock. NOT FIXED.
9. **Inert `RELAX_STRAGGLER_TOPOLOGY_EPOCH` (S1).** Nothing in the tree derives
   or updates it; it is read from the environment only, so a re-shard is
   invisible to the cohort key unless an operator sets the variable by hand.
   KNOWN LIMIT.
10. **No rollout/topology reset (S2).** There is no rollout or topology reset of
    the streak/active state, so a stall spanning a rollout boundary is drained
    into the next rollout's perf log. KNOWN LIMIT.
11. **`MAX_SAMPLES_PER_RANK` can drop a late slow tail (E3 cap).** A rank fast
    for the first cap-sized run of samples and slow afterwards can be a false
    negative; the drop is counted and published as `sample_evictions`, but the
    cap itself was deliberately not changed. NOT FIXED. (Observed as
    `sample_evictions=0` in `abba-ce9b637/S1-on/run_10000000/collector_status*.json`.)
12. **Attention and MoE have no real timer coverage** anywhere in the pinned
    Megatron stack (core 0.19.0 emits no attention/MoE/router/dispatch/combine
    timer); they stay schema-only and unsupported, never faked.
13. **Collector-versus-export rank mismatch under `pp_size > 1`:** the collector
    is created at global rank 0 while the platform merge runs on the Megatron
    primary rank (tp0, pipeline-last, dp0), which coincide only when
    `pp_size == 1` and `cp_size == 1`; the exporting rank now emits
    `collector_status_available = 0` instead of exporting silently. Not fixed.
14. Also still open per the RFC body: message budget, collector CPU cost and rank
    scaling are unmeasured; the collector is same-host only; CUDA-event
    intervals are GPU-stream intervals, not CPU launch stalls, and a
    communication-named timer is an observable interval, not NCCL kernel time;
    workload publishing covers the SFT prepack path only; earlier
    `workload_incomparable` counts (e.g. the 1403-envelope run) are
    unit-contaminated and not reusable; there is no authoritative cumulative
    optimizer-step counter.

**The four documentation-versus-behaviour contradictions** (measured, recorded,
not fixed — PR #378 body):

1. `reporter.py` claims it never blocks the training thread and performs no I/O,
   yet with INFO logging it writes three lines synchronously (`report_once` p50
   34.5 µs → 83.5 µs).
2. `report_once`'s "enabled but no runtime" branch is unreachable through the
   public API, so the `collector_status_available=0` marker comes from the
   collector-ownership check, not that branch (confirmed in
   `/tmp/straggler_latency_results.json`, `probe_runtime_none_branch`
   `public_state_can_reach = false`).
3. The timer shim says start/stop only record a timestamp and optionally a CUDA
   event, yet on the no-CUDA path `stop()` also builds the envelope and calls
   the consumer inline.
4. The observer's "nothing may block on the training thread" is loose on the
   host-only path.

## Test summary

Command actually run in this session:

`cd /root/autodl-tmp/relax-work/task11-c2 && /root/autodl-tmp/venv-e2e/bin/python -m pytest tests/utils/straggler -q 2>&1 | tail -2`

Exact final line:

```
350 passed, 2 skipped, 14 warnings in 48.40s
```

Context, for honesty about the public text: the RFC #357 and PR #378 bodies
still report `347 passed, 2 skipped, 14 warnings in 48.35s` at the documented
freeze `ce9b637`. The increase of 3 tests is consistent with the post-freeze
commit `cac4cb6`, whose `git show --stat` adds
`tests/utils/straggler/test_straggler_readout_order.py` (+216 lines) alongside
the `relax/utils/straggler/observer.py` change. The 2 skips are the legitimate
"requires the relaxed training stack (Megatron + transfer_queue)" class with
explicit reasons. No full-repository clean pass is claimed; the bodies describe
the full suite as unable to run cleanly here (missing optional deps).

## CI / review state

Source: `gh pr view 378 --repo redai-studio/Relax --json state,isDraft,reviewDecision,mergeable,mergeStateStatus,statusCheckRollup,headRefName,headRefOid,baseRefName,url,title,createdAt,updatedAt`.

| field | value |
| --- | --- |
| `state` | `OPEN` |
| `isDraft` | `true` |
| `reviewDecision` | `REVIEW_REQUIRED` |
| `mergeable` | `MERGEABLE` |
| `mergeStateStatus` | `BLOCKED` |
| `statusCheckRollup` | `[]` — **no CI checks reported** |
| `headRefName` | `feat/task11-straggler-profiler` |
| `baseRefName` | `main` |
| `headRefOid` | `cac4cb6447154e6ae4f563eabab7fecf43dba790` |
| `createdAt` / `updatedAt` | `2026-09-25T16:29:02Z` / `2026-09-26T04:01:00Z` |

Review state: **no review and no comment exists.** All three API reads returned
empty: `gh api repos/redai-studio/Relax/issues/378/comments` (empty),
`.../pulls/378/comments` (empty), `.../pulls/378/reviews` (empty). The PR body's
checklist matches: "Review comments addressed one by one (none yet — Draft PR)"
unticked and "CI passing (no checks are reported on this Draft PR / fork head)"
unticked. The RFC #357 object reports `updatedAt` `2026-09-26T03:54:20Z`.

## Exact RFC final text

Source: live GitHub object, `gh issue view 357 --repo redai-studio/Relax --json
body,updatedAt -q .`, `updatedAt` `2026-09-26T03:54:20Z`. Reproduced verbatim.
(A checked-out copy also exists at
`/root/autodl-tmp/relax-work/RFC357_C2_FINAL.md`, but it is an **older
revision** — 18347 bytes naming HEAD `47581e0`, versus 38752 bytes live — so the
live object is used here.)

```text
## Summary

**Status: IMPLEMENTED (mechanism); acceptance PARTIAL.**

**This is IMPLEMENTED, not planned.** `relax/utils/straggler/` exists and is wired into the Megatron backend, and the default deployment is unchanged because the profiler is default-off. Acceptance is **PARTIAL on all three official criteria** (see *Official acceptance*); none is met. Earlier status text in this body claimed the mechanism was not yet integrated into Relax and that only a plan existed; those claims were false and have been removed.

What exists today:

- a Megatron timer shim that replaces `config.timers` without blocking the host;
- an in-process observer with bounded structures, which stamps the wire sequence at interval **completion** (see E1 below);
- an out-of-band rank-0 collector reached over TCP;
- a detector that produces verdicts carrying `facts` and `candidate_causes`;
- reporting merged into the **existing** platform perf request as `perf/straggler/*`.

It observes only: it never kicks a rank, never changes the training schedule, and adds no training-path telemetry collective.

The three differentiators — no training-path telemetry collective, a strictly bounded and failure-isolated observer, and topology-aware equivalent peer cohorts — describe the mechanism and are each pinned by a test. They do **not** imply complete stage coverage. Before `08184e6`, Megatron's enclosing level-1 `forward-backward` interval took its sequence at start while being delivered at completion, so the collector classified it `late` and dropped it unjudged: on a real 4-rank run where one rank stalled only inside `forward-backward`, the pre-fix code reported `late_packets=16` and zero straggler verdicts. Whole-phase coverage was therefore **not** complete on GPU runs before `08184e6`; attention and MoE remain schema-only.

## Scope and non-goals

**Status: IMPLEMENTED.**

Scope (first phase): text-dense training on the Megatron backend; per-stage host/device timing taken from the existing Megatron timer call sites; a same-host, out-of-band collector; token-based comparable cohorts; verdicts that separate measurements from candidate causes; merge into the existing perf log.

Non-goals: it is not a hardware-fault detector and never concludes a bad GPU/NIC from a stage name or from lateness alone; it does not rebuild global pipeline bubbles or deliver chunk-level VPP diagnosis; attention and MoE are schema-only and unsupported; there is no bilingual docs page yet; no per-op trace; no new training collective; no scheduler or admission change.

## Design invariants

**Status: VALIDATED.** Each invariant has an enforcing test under `tests/utils/straggler/`.

- **No training-path telemetry collective — the first differentiator.** Cross-rank aggregation never rides a training NCCL/Gloo group; ranks ship envelopes out of band to the collector. Enabling the profiler adds no collective to the training step. An AST/source guard over the package plus a runtime instrumentation test drives the real timer → observer → sender → socket → receiver → collector path and asserts zero forbidden calls.
- **Default-off.** With `RELAX_STRAGGLER_ENABLE` unset, `get_straggler_timers()` returns `None` and Megatron's `config.timers` is left as upstream.
- **Readback happens off the training thread.** A timer `start`/`stop` only records; CUDA event readback runs on a daemon thread.
- **Never synchronise.** No `cuda.synchronize`, no `barrier`; Megatron's `barrier=True` is accepted and counted as suppressed.
- **The observer is failure-isolated and bounded.** It has a terminal state machine (`active`→`degraded`→`disabled`), a fixed counter-key set, and hard caps on the event pool, pending tokens, queue length, dedup, windows, verdicts, streaks, active triples and label/name tables. Every drop and eviction is counted and never raised.
- **Wire sequence follows completion order.** The sequence is allocated in `complete_interval`, so an enclosing timer that finishes last is not delivered behind the interval it wraps; a genuinely stale resend still lands behind the newest sequence for its rank and is still classified `late`.
- **Reporting is an adapter, not a new pipeline.** It reads in-process counters and drains verdicts without I/O, then merges into the existing perf request.
- **Peer cohorts are topology-aware.**

## Architecture

**Status: IMPLEMENTED.**

1. **Timer shim (`megatron_timer_shim.py`).** A drop-in `config.timers` object with Megatron's call shapes and log-level filtering. Per existing timer call it adds one host timestamp and, when device timing is available, one CUDA event record on the current stream. It never reads an event back and never synchronises; a bounded timer-name table and counted barrier suppression keep unknown names inert.
2. **Observer (`observer.py`).** Owns a preallocated pool of CUDA event pairs, a bounded pending deque and one daemon readout thread; builds a `TimingEnvelope` per interval with the rank identity and the training context. The wire sequence is stamped when the interval completes, not when it starts (E1). Pool exhaustion degrades one interval to host-only timing; a full queue drops it with a counted reason.
3. **Collector (`collector.py`, `runtime.py`).** Same-host TCP. With `RELAX_STRAGGLER_COLLECTOR_ADDR` set, global rank 0 binds and ingests while non-zero ranks run a background sender; with the address unset each process keeps a rank-local collector. The collector validates packets, dedups on `(run_id, topology_epoch, global_rank, sample_seq)` while a key is retained within a TTL, counts malformed/duplicate/late packets, and keeps every judgement structure bounded.
4. **Detector (`detector.py`).** Aligns windows per cohort, computes per-stage medians, applies the absolute-magnitude floor and the **per-rank** token comparability gate, tracks persistence, and emits verdicts. Per-window workload is the median of a rank's per-sample readings, so arrival order cannot flip a verdict.
5. **Reporting (`reporter.py`, `utils/training/train_metric_utils.py`).** `report_once` reads the runtime's non-flushing `summary()` and drains pending verdicts, returns `perf/straggler/*` scalars, and `log_perf_data_raw` merges them with `log_dict.update(...)` into the already-made perf log dict before the single existing platform write. No new request is created.
6. **Context (`context.py`).** The training loop publishes `rollout_id`, the in-rollout `optimizer_step`, an optional caller-supplied `global_step`, this rank's per-step workload, and the profiler's own monotonic `step_ordinal` into one frozen slot: no I/O, no collective, no device sync.

## Measurement semantics

**Status: IMPLEMENTED.**

**Windows are bounded TIME windows (default 5 s), not optimizer-step aligned.** The envelope carries `rollout_id`, `optimizer_step` and `sample_seq` as context only.

**Comparability is decided by TOKENS ALONE** against the peer median with a relative `work_tolerance` (default 0.05). `sequences_delta` and `microbatches_delta` are evidence that never enters the decision; `workload_comparable` is carried in the facts. This is the accepted cost of the frozen rule. Accepted consequence, recorded verbatim: `{1000 tokens, 1 sequence, 1 microbatch}` beside `{1000 tokens, 1000 sequences, 100 microbatches}` yields `workload_incomparable_windows=0` and judges the third rank a straggler with `workload_comparable=True`, `tokens_delta=0.0`, `sequences_delta=999.0`, `microbatches_delta=99.0`.

Summing tokens + sequences + microbatches was wrong in both directions:

- rank `{tokens:100000, sequences:1, microbatches:1}` against peers `{tokens:95000, sequences:5000, microbatches:1}` sums to a 0.001 % difference and was judged comparable, while the token workload really differed by **+5.26 %**;
- a rank `{tokens:100000, sequences:1}` against a peer `{tokens:100000, sequences:6300}` sums to a 5.93 % difference and was flagged incomparable although the token workloads were identical.

The gate is a **per-rank** test: a rank whose own tokens are within tolerance of its peer median is judged even when another rank of the same pair is not. Evaluating it pair-wide let one over-worked peer withhold an unrelated equal-work straggler (E4).

Previously reported `workload_incomparable` conclusions are unit-contaminated and flip in both directions, so they must not be reused as if only the statistic changed.

**Absolute-magnitude floor.** `min_stage_ms` (default 5 ms) rejects a stage or a gap below the floor: there the relative deviation is host/launch jitter, so the window is `uncertain`/`below_absolute_floor` and counted, not tuned to zero. A stage is judged only when the gap exceeds **both** 5 % of the fastest peer **and** 5 ms; below ~100 ms the 5 % relative tolerance is not the binding constraint, so a 10× slowdown on a 0.4 ms stage is invisible by construction and a 10× slowdown on a 2.9 ms stage is reported `uncertain` rather than `straggler`. This is a documented tradeoff, but it is a systematic false negative and is listed as a known limit.

**Missing workload is degraded, not equal.** A rank that published no workload, or that has no peer to compare against, records `workload_reported=False`, `workload_comparable=None` and `workload_evidence_degraded=True`, is counted in `workload_missing_windows`, and is **not** withheld from the timing judgement: absence is a degraded measurement, never read as equal work.

**Measurement classification.** Verdicts carry the raw `stage` plus facts. `facts` and `candidate_causes` are deliberately separate; the default cause is `undetermined`, and a cause is only asserted from measured facts — never from a stage name. The measurement labels distinguish CUDA-timeline from GPU-busy: `host_only_stall`, `gpu_stream_stall` and `attribution_unknown`.

**Step identity.** `optimizer_step` is an in-rollout index, documented as such; `global_step` is `Optional` and stays `None` unless a caller supplies a genuinely run-wide value, and is omitted from the metric when `None`; a new monotonic, collision-free `step_ordinal` is assigned by the profiler for ordering. A 4-step rollout followed by a 1-step rollout yields ordinals `[1,2,3,4,5]`, whereas the inherited platform arithmetic `rollout_id * num_steps_per_rollout + optimizer_step` gives `[0,1,2,3,1]` and is **non-monotonic**. That non-monotonicity is pre-existing upstream behaviour (`relax/utils/replay/schema.py` and `docs/en/guide/trajectory-replay.md` already document it); our defect was only that an API had been widened to depend on a single derived value, and that widening was removed. It is not presented as an upstream bug this work discovered or fixed, and it is not papered over.

## Equivalent cohorts

**Status: IMPLEMENTED (with one inert input — see Known limits).**

A cohort is a topology-aware equivalence class: `topology_epoch`, `stage_schema`, TP, PP, VPP, chunk, CP, EP and ETP are all in the key. The data-parallel axis is deliberately excluded because that is the axis the comparison runs along (expert-data-parallel replicas are excluded the same way); EP and ETP are included because ranks holding different experts execute genuinely different work. A rank with no equivalent peer is recorded but never judged; a single-rank window is counted `incomplete_windows` (or `single_rank_windows` for a genuine world size of 1). Coverage is reported against the expected cohort size; the envelope's `world_size` is only a fallback and can overstate the cohort, which makes coverage conservative rather than flattering.

## Failure model

**Status: VALIDATED.**

- **Shim:** every entry point degrades to a no-op; suppressed barriers, unbalanced start/stop and level mismatches are counted, never raised.
- **Observer:** pool exhaustion → host-only interval; full pending queue → counted drop; readout timeout, consumer error and observer error are counted; 64 cumulative failures disable it permanently. `disabled` is terminal, so the profiler cannot flap and leave gaps, and while disabled recording is a counted no-op that creates no event and starts no thread.
- **Sender:** bounded queue, counted drops, reconnect, no backpressure into training; a collector restart is tolerated.
- **Collector:** malformed, duplicate, late and out-of-order packets are counted and excluded from judgement; every structure is capped with counted evictions. The collector serialises its shared state with a re-entrant lock; file I/O never runs under that lock. However, `ingest` calls the periodic-summary path while still holding the state lock, so that summary log is emitted under the lock (E12).
- **Reporter / context:** never raise and count swallowed failures; workload guard rejections and errors are counted (`workload_publish_skipped` / `workload_publish_errors`).
- A corrupted CUDA context that makes training itself fail is **not** "graceful degradation", and missing observations are never zero-filled: an unmeasured key is omitted so it reads as "not measured".
- **Counters are consistent.** Malformed envelopes are counted as `observe_errors`/`invalid_samples`, not as `uncertain_judgements`; every emitted `uncertain` verdict increments `uncertain_judgements`; and `stragglers_reported` increments only in the exact window where the persistence threshold is first crossed, so a stall that is re-evaluated after its active entry was evicted is not counted twice (E8).
- **Drops are published.** `perf/straggler/dropped` sums every detector eviction counter (including `sample_evictions`, the `MAX_SAMPLES_PER_RANK` cap), the collector's pending-line drops, and the malformed-sample counters, so a window that dropped samples cannot publish no drop at all (E3).
- **Rank mismatch is marked, not silent.** The collector is created at global rank 0 while the platform merge runs on the Megatron primary rank (tp0, pipeline-last, dp0). Those coincide only when `pp_size == 1` and `cp_size == 1`. Under `pp_size > 1` the exporting rank owns no collector, and the reporter emits `perf/straggler/collector_status_available = 0` for it (and `1` for the rank that owns one) rather than going quiet; the underlying mismatch is still a limitation.

## Official acceptance

**Status: PARTIAL on all three criteria. None of the three is met.**

**Criterion 1 — overall overhead below 0.5 %: PARTIAL, not yet demonstrated.** The paired OFF/ON campaign is not complete. There is a single-session point estimate: `step_time` median −0.118 % (0.9262 s vs 0.9251 s, OFF vs ON) and mean +2.558 % (1.9208 s vs 1.9699 s), the mean driven by a startup tail. Whole-run wall clock, throughput, p50/p95/p99 and a startup-versus-steady-state split were **not captured** by that session, so the criterion is not yet demonstrated. Design bounds and microbenchmarks are supporting evidence only and are never acceptance evidence. The mean is not dismissed as an outlier and acceptance is not announced on the median alone.

**Criterion 2 — end-to-end without harming accuracy, loss or the existing compute/communication overlap: PARTIAL.** What exists: a default-off, failure-isolated design that adds no synchronisation and no collective to the training path, plus historical run comparisons of loss and parameters. What is still missing: a short-trace check of compute/communication overlap on the final build and a paired accuracy/overlap campaign on the code that ships.

**Criterion 3 — real-time reporting and easy localisation: PARTIAL.** Platform reporting is at **rollout cadence**, on the training thread, from the primary rank only, and it rides the existing path: `report_once` returns `perf/straggler/*` scalars and `log_perf_data_raw` merges them with `log_dict.update(...)` into the same dict the pre-existing platform write already sends. No new HTTP request and no new collective is created. The merge is failure-isolated (wrapped in `try`/`except`; the handler only emits a debug log), so a straggler failure cannot affect the perf metrics. One nuance bounds the claim: the `perf <rollout_id>` INFO line is emitted **before** the merge, so that log line does **not** contain the straggler keys; the keys reach the platform metric record through the existing write, not through that INFO line, and an operator grepping the training log for `perf <rollout_id>` will not see them there. The collector's own periodic summary and its runtime/collector status JSON files are **log and file evidence, not platform metrics**, and are not presented as platform reporting. Therefore collector diagnosis is near-real-time (window default 5 s, after warmup and persistence) while platform export is rollout-cadence. No already-safe asynchronous publish path exists in this repo: a MetricsService deployment exists, but its only client publishes with blocking HTTP from the training thread (the adapter calls `log_metrics_batch(..., immediate=True)`, a `requests.post` with a 5 s timeout), so it was deliberately not used, and no training-thread HTTP, blocking queue or new collective was added. The hop latencies were measured in-process on the real shim, observer, collector, detector and `report_once`, with a fake CUDA-event backend and a manual clock (Xeon 8352V, Python 3.12, torch 2.11.0+cu130; 20 000 iterations per variant over three runs, 4 000 for the verdict): interval completion to ingest p50 **20.3 us** (p99 35.5 us) on the host-only path; last-envelope ingest to window verdict p50 **52.1 us** (p99 87.7 us) when a later envelope triggers the close and **36.7 us** (p99 64.8 us) on `flush()`; `report_once` p50 **34.5 us** populated, **24.7 us** with nothing to report, **83.5 us** when the root logger is at INFO (about 2.4x the log-suppressed call), and **0.75 us** when the profiler is disabled. One start/stop pair costs a paired p50 delta of **7.9 us** over a `_NoopTimer` control with a no-op consumer, **23.4 us** when the local collector ingests inline, and **14.3 us** on the paced device path. A structural result matters more than the number: ingesting the **last** envelope of a window produced **no verdict** in 4 000 of 4 000 iterations, because a verdict needs a later envelope beyond `WINDOW_GRACE` or a `flush()`. There is no timer-driven verdict, so the wall-clock wait from a window's end to its verdict is schedule-dependent and is not measurable without a real interval cadence. These are CPU proxies with a fake device backend: they bound in-process Python cost only, they are **not** a GPU measurement, and the tight-burst device figure from the same harness is a GIL-starvation upper bound of the synthetic producer rather than a device latency. Under `pp_size > 1` the collector-versus-export rank mismatch is a stated limitation, now marked by `collector_status_available`.

Localisation: verdicts carry the raw `stage` plus facts and candidate causes; `facts` and `candidate_causes` are deliberately separate and the default cause is `undetermined`; the measurement labels distinguish CUDA-timeline from GPU-busy (`host_only_stall`, `gpu_stream_stall`, `attribution_unknown`); and the absolute-magnitude floor, the per-rank workload-comparability gate and the completion-order sequence are real, counted behaviours.

## Evidence

**Status: VALIDATED for the mechanism; PARTIAL for acceptance.**

Frozen state: code-freeze SHA `ce9b637635220e218225f3b001898334754cec14`, working tree clean, pre-commit green on the changed file set. One summary table; statistical detail (estimators, intervals, plots) lives in the evidence document, not here.

| Evidence | Result | What it supports |
| --- | --- | --- |
| Straggler suite at the freeze SHA | `347 passed, 2 skipped, 14 warnings in 48.35s` (`pytest tests/utils/straggler -q`) | The mechanism is covered. The 2 skips are the legitimate "requires the relaxed training stack (Megatron + transfer_queue)" class with explicit reasons, not skip-as-a-fix. |
| Full repository suite at the freeze SHA | With `--continue-on-collection-errors`: `65 failed, 2358 passed, 401 skipped, 8 errors`. Cleanly it aborts with collection errors because optional deps are missing. **Zero** of those failures are attributable to this work. | Honest environment statement: the failures are `transfer_queue`, `pylatexenc`, `diffusers`, `audioread` and `megatron` missing, plus the environment-gated `tests/backends/megatron/test_gdn_cp_gpu.py`. No clean full-suite pass is claimed. |
| Single paired OFF/ON session (only point estimate) | `step_time` median −0.118 %; mean +2.558 % | The mechanism runs end-to-end. Criterion 1 remains **not yet demonstrated**: whole-run wall clock, throughput, p50/p95/p99 and a startup-versus-steady-state split were not captured, and neither the mean nor the median alone decides it. |
| Paired campaign | Not complete | Cannot decide <0.5 %. Design bounds and microbenchmarks are supporting evidence only, never acceptance evidence. |
| E1 nested timers (fixed at `08184e6`) | Before the fix, an executed 4-envelope nested case gave 4 in, 3 judged, 1 late; a 4-rank run where one rank stalled only inside `forward-backward` gave `late_packets=16` and zero straggler verdicts. After the fix, the regression test drives the real shim, observer and collector with a fake CUDA-event backend, asserts zero late packets, every packet judged, and a `host_only_stall` straggler verdict on the enclosing interval; it was proven to fail against the start-time ordering (24 late packets, no verdict). | The whole-phase interval is judged after `08184e6`; coverage was **not** complete before it. |
| E4 over-worked peer (fixed at `acfafb2`) | Executed counterexample: hosts 100/100/100/300 ms with tokens 1000/1200/1000/1000 made rank 3 `uncertain`/`workload_incomparable` although its own facts said `tokens_delta=0.0`. After the fix rank 3 is a straggler with `tokens_delta=0.0` and `workload_comparable=True`, pinned by `test_over_worked_peer_does_not_withhold_an_equal_work_straggler`. | Comparability is a per-rank test. |
| E10 arrival order (fixed at `acfafb2`) | The same samples fed in two arrival orders now give identical verdicts and facts (rank 0's readings 1000/1000/2000; median 1000), pinned by `test_workload_aggregate_is_arrival_order_independent`. | The per-window workload is order-independent. |
| E3 coverage and drops (reporting corrected at `18c8a95`) | `perf/straggler/coverage` is emitted only from an explicit cohort coverage ratio; the old `judged_packets / envelopes` fallback was moved to its own truthfully named key `perf/straggler/judged_fraction`. The previous metric could read 1.0 on a run whose real cohort coverage was far lower. `perf/straggler/dropped` now sums the detector eviction counters, including `sample_evictions`. | The metric's value matches its name; a cap that dropped data is visible. |
| E8 counter consistency (fixed at `acfafb2`) | Malformed samples increment `observe_errors`/`invalid_samples`, not `uncertain_judgements`; every `uncertain` verdict increments `uncertain_judgements` (a sub-floor window that emits three uncertain verdicts no longer leaves it at 0); `stragglers_reported` increments only at the onset window, so an evicted active entry is not re-counted. | The counters say what their names say. |
| Workload-producer correction | Published after the DP-wide K decision, as the step total | The per-step workload used to be published from the rank-local partition, while training executes the DP-wide `max_k` partition and repacks when `local_k < max_k`, so the metadata could describe a discarded partition. It is now published after that decision, re-derived with the same pure deterministic function and the same inputs. The call site runs one optimizer step over all `max_k` micro-batches, so the tip publishes one entry per optimizer step with that step's totals (`tokens=sum(samples)`, `sequences=len(samples)`, `microbatches=max_k`). |
| Recorded ON run (1403 persisted envelopes, all one microbatch and eight sequences, 57 `workload_incomparable` windows, 253 uncertain verdicts, zero stragglers) | **NOT reusable evidence** | Those counts are unit-contaminated by the old summed-work rule (tokens + sequences + microbatches), and the archived run never exercised the repack branch because `max_k == 1` throughout. It cannot be cited for the comparability gate or for the repack fix. |

## Trade-off against an alternative design

**Status: IMPLEMENTED (design); two questions remain open.**

An alternative design collects in band with a periodic all-gather and judges on the primary rank, and carries its metrics through an optional parameter on the existing perf call. This work uses an out-of-band TCP collector and per-sample envelopes, adds no training-path collective, and merges into the existing perf request without changing its signature. The cost is one more transport and a service lifecycle to operate; the benefit is that no training collective is introduced and per-sample evidence is retained.

This is not a claim that this design is better. If maintainers choose one mainline, collection-fault isolation, per-sample diagnosis and the validation set can land as incremental contributions rather than maintaining two same-function paths. Two questions remain open, and they are the reason to decide on evidence rather than design taste: (1) does training stay unaffected under report timeout, collector restart and backlog; (2) does per-sample recording add localisation beyond window aggregates while total cost still fits the threshold.

**REAL-GPU CORRECTION (2026-09-26, first fresh paired session at `ce9b637`).** The completion-order change (`08184e6`) is NOT sufficient on real hardware and its "FIXED" status is downgraded. In a 48-step DP4 ON run the collector reports `envelopes=2069 judged=1455 invalid=0 duplicate=0 late=614` - **29.7% of every envelope is discarded as `late`** - and the enclosing `forward-backward` interval was judged **0 times**, while the level-2 timers beneath it (`forward-compute`, `backward-compute`, plus communication and optimizer stages: 9 distinct raw names) were judged normally. So the phase-wrapper stall the fix was meant to expose is still invisible, and the CPU-harness result does not transfer. Coarse-stage presentation is nevertheless confirmed live on hardware: real verdicts are emitted as `straggler stage: name=params-all-gather coarse_stage=communication`, carrying both the raw timer name and the coarse group. The cause is now identified from the persisted envelopes: in real Megatron the per-step completion order places `forward-compute` in slot 1 and `backward-compute` in slot 2, but the enclosing `forward-backward` interval completes in slot 7 - **not last** (`params-all-gather` takes slot 11) - and `forward-backward` loses 18 of 48 instances per rank (30, 30, 32 and 41 of 48 across the four ranks), while `optimizer-inner-step` loses 4. The dedup layer declares any envelope whose sequence is below the newest already seen for that rank to be `late` (631 of 2112 here, with `invalid=0 duplicate=0`), which is only sound when arrival order equals completion order. It does not: several intervals per rank are in flight at once, the long level-1 interval is built and delivered after shorter, higher-sequence intervals from the same step, and it is then discarded as `late`. A phase-level coverage claim is therefore withdrawn for this build. The CPU harness passes only because its delivery is strictly ordered, so the completion-order change alone was never the whole fix; the dedup ordering rule itself has to change. A blanket in-flight tolerance was implemented and then **refuted by the existing suite**: relaxing the ``seq < newest`` comparison to ``seq < newest - tolerance`` accepts the real-GPU ordering but breaks 7 pre-existing tests, including the red-team conservation test and the per-rank ordering and packet-class conservation tests, because those pin the strict contract deliberately. The change was therefore reverted and the tree is back at ``ce9b637`` with 347 passed and 2 skipped. The defect is in the observer's delivery order, not in the dedup rule, and this is now pinned to a line: `_readout_until_stopped` pops `_pending` in completion order, and when `_process` reports that an interval is not yet readable it re-queues the token with `self._pending.append(token)` - **at the tail**. A deferred token is therefore delivered after every later, higher-sequence token, so the collector sees a sequence regression and drops it as late. That is exactly the observed shape: the longest interval, `forward-backward` in slot 7, is the one most likely to need a retry and loses 18 of 48 instances, `optimizer-inner-step` in slot 9 loses 4, and the short intervals in slots 1, 2 and 11 lose none. The CPU harness cannot show this because nothing there is ever deferred, so its delivery stays strictly ordered. The fix therefore belongs in the readout loop, which must preserve sequence order under retry without allowing head-of-line blocking, and the strict late contract - and with it all seven pre-existing tests - can then stand unchanged. No test was weakened or removed.

First fresh paired session (same commit, GPU set, recipe, seed and step count; only `RELAX_STRAGGLER_ENABLE` differs; 48 optimizer steps each, processed fresh): `perf/train_time` OFF median 15.8572 s vs ON 15.8753 s, paired median delta **-0.028%** and paired mean delta **-1.402%** (max |delta| 4.83 s); `perf/actor_train_time` paired median delta **-0.048%** and paired mean delta **-2.008%**. One session only: no session-aware interval is computable, whole-run wall clock, throughput, p50/p95/p99 and the startup/steady-state split were not captured, and both arms ran under a machine load near 50 with about 35 s per step against 6.5 s per step in the archived arms, so this pair is internally consistent but not comparable with the archived sessions. Criterion 1 remains **PARTIAL / not yet demonstrated**.

## Known limits

**Status: PARTIAL — every item below is an explicit, tracked limitation, not vague future work.**

- **E2 — a restarted observer is still blacklisted.** The dedup tracker's `_seen` map has a TTL, but its `_newest` map is evicted only by entry count and never by time. Under a stable `run_id`, a restarted rank whose sequence restarts at 1 has every low sequence compared against the retained high-water mark and returns `late` until the cap evicts that rank key. NOT FIXED.
- **E3 (cap) — `MAX_SAMPLES_PER_RANK` still drops a late slow tail.** A rank fast for the first cap-sized run of samples and slow afterwards can be a false negative. The drop is now counted and published as `sample_evictions`, but the cap itself was deliberately not changed because it is the detection algorithm rather than a reporting defect. NOT FIXED.
- **E5 — `peer_median_ms` includes the rank itself.** The published timing `peer_median_ms` is a median over all ranks of the pair including the rank being judged; the workload gate correctly excludes self, and detection uses the minimum, so this mislabels evidence without changing a verdict. NOT FIXED.
- **E6 — the floor-times-tolerance gate is a systematic false negative.** A stage is judged only when the gap exceeds both 5 % of the fastest peer and 5 ms, so the relative tolerance only binds above ~100 ms and a 10× slowdown on a 0.4 ms stage is invisible; a 10× slowdown on a 2.9 ms stage is `uncertain`/`below_absolute_floor`, never `straggler`. Documented tradeoff; NOT FIXED.
- **E7 — `cohort_below_min_size` is dead at the default.** The config clamps `min_cohort_size` to a floor of 2 and the smaller-cohort (`cohort_size < 2`) case returns earlier, so the `cohort_size < min_cohort_size` branch is unreachable at the default. It is meaningful only when `min_cohort_size >= 3`, where it makes every rank of a healthy 2-rank window `uncertain` (with `workload_comparable=None` and `workload_evidence_degraded=True`, so the reason and the facts agree). The guard was kept, not removed. NOT FIXED.
- **E9 — a peer packet delayed by more than two windows is lost rather than compared.** `WINDOW_GRACE` is 1 window (default 5 s) while the observer's readout timeout is 30 s. Such a packet recreates its old window, which is then immediately closed as too old and judged with a single rank, so it is counted `incomplete` instead of compared. NOT FIXED.
- **E11 — the workload stamp is taken after the interval closed.** The envelope's workload is read when the envelope is built, on the readout thread, after the interval completed, so it can belong to a later rollout or step than the interval it rides. The envelope's only temporal anchor for the interval is `host_start`; the workload stamp is advisory. The fix would live in `observer.py`. NOT FIXED.
- **E12 — the no-CUDA path runs detection on the training thread and logs under the state lock.** Without device timing (or when an interval has no event pair), the observer delivers the envelope synchronously on the training thread, so a rank-local or rank-0 collector runs `detector.observe` there; `ingest` also calls the periodic-summary path while holding the collector's state lock, so that log line is emitted under the lock. NOT FIXED.
- **S1 — the topology epoch is inert.** Nothing in the tree derives or updates `RELAX_STRAGGLER_TOPOLOGY_EPOCH`; it is read from the environment only, so a re-shard is invisible to the cohort key (the cohort string is unchanged) unless an operator sets the variable by hand. KNOWN LIMIT.
- **S2 — no rollout or topology reset.** There is no rollout or topology reset of the streak/active state, so a stall spanning a rollout boundary is drained into the next rollout's perf log. KNOWN LIMIT.
- **S3 — an unbounded far-future `host_start` can force-close pending windows.** `protocol.validate()` never inspects `host_start`, and a finite far-future value is accepted; because the detector closes the oldest window once `newest - oldest > WINDOW_GRACE + 1`, one such sample can flush every pending window early. NOT FIXED.
- **Attention and MoE have NO real timer coverage anywhere in the pinned Megatron stack** (core 0.19.0 emits no attention/MoE/router/dispatch/combine timer). They stay schema-only and unsupported, never faked; splitting them out would need a deep hook that is out of the first phase.
- **Collector-versus-export rank mismatch under `pp_size > 1`:** the collector is created at global rank 0 while the platform merge runs on the Megatron primary rank (tp0, pipeline-last and dp0), which coincide only when `pp_size == 1` and `cp_size == 1`. PP>1 is explicitly out of scope for this first phase; `collector_status_available` now marks the exporting rank as unavailable rather than exporting silently.
- The message budget, collector CPU cost and rank scaling are unmeasured.
- Same-host only (the collector is a same-host TCP socket).
- CUDA-timeline semantics: a CUDA-event interval is the GPU stream interval, not a CPU launch stall, and a communication-named timer is an observable interval, not NCCL kernel time.
- Workload publishing covers the SFT prepack path only; the RL main path, the streaming path and non-prepacked SFT leave `workload` absent rather than guessed.
- `workload_incomparable` counts recorded before the token-only fix are unit-contaminated and are not usable evidence; the 1403-envelope run is not reusable (see *Evidence*).
- There is no authoritative cumulative optimizer-step counter to read; `global_step` is context, not an identity.
- The three hop latencies are measured only as CPU in-process proxies with a fake device backend (see criterion 3). They bound in-process cost and are not a GPU measurement, and the device-path delivery figure from that harness reflects the fake backend waiting on a simulated event rather than a real device latency.

## Implementation status

**Status: IMPLEMENTED.**

Fix commits since the previously-cited `5ed640c`, oldest first; the freeze head is `ce9b637`:

| commit | change |
| --- | --- |
| `6293d3b` | `ray-job.sh` warn-only probe for a live Ray job behind a free GPU lock; the acquisition/cleanup/sidecar block itself had landed in `d0b4eeb` after a concurrent agent swept it into a straggler commit. |
| `acfafb2` | Judge workload **per rank** and aggregate it order-independently (median of per-sample token readings); fixes the pair-wide gate that let an over-worked peer withhold an equal-work straggler (E4) and the last-arrival-wins workload (E10). Also fixes the counter contradictions (E8). |
| `18c8a95` | Step context in-rollout only: `global_step` optional, `optimizer_step` documented, monotonic `step_ordinal` added; surface the publish/gate counters; correct coverage/judged-fraction and the `dropped` aggregate (E3); mark the PP>1 exporting rank. |
| `08184e6` | Stamp the interval sequence at **completion** so nested timers are judged (E1), with a regression test that drives the real shim/observer/collector. |
| `d3ca9e3` | Ruff format on the reporter tests. |
| `ce9b637` | Ruff + docformatter on the audited files. |

Earlier history from `dc1cbee` to `5ed640c` (workload publish order, `train_one_step` signature restored, publish gating, step-total publish, pure workload module, stage taxonomy) is unchanged and is not repeated here.

**Commit attribution.** Concurrent agents working in one worktree caused some changes to be swept into another agent's commit by a `git add -A`, so commit granularity does not perfectly map to authorship. History was deliberately **not** rewritten. This table attributes changes by content, not by author.

Registered tests that pin the fixes:

- `tests/utils/straggler/test_straggler_nested_timers.py` drives the real shim, observer and collector over a fake CUDA-event backend and asserts the enclosing `forward-backward` interval is judged and reported.
- `tests/utils/straggler/test_straggler_detector.py` pins the per-rank workload gate, the order-independent aggregate, the counter semantics and the floor.
- `tests/utils/straggler/test_straggler_reporting.py` pins coverage vs `judged_fraction`, the `dropped` aggregate and the `collector_status_available` marker.
- `tests/utils/straggler/test_straggler_workload_publish_runtime.py` is now a **registered** test that drives the real SFT prepack path; in a CPU-only environment it skips with the explicit "requires the relaxed training stack (Megatron + transfer_queue)" reason rather than failing. The earlier claim that this harness existed only as an untracked work-in-progress file is stale and has been removed.
- The rest of the suite under `tests/utils/straggler/` covers the shim, observer, protocol, detector, collector, runtime, reporter and invariants.

GitHub checks: none reported on the current Draft PR / fork head.







```

## Exact PR final body

Source: live GitHub object, `gh pr view 378 --repo redai-studio/Relax --json
body,headRefOid,updatedAt -q .`, `headRefOid`
`cac4cb6447154e6ae4f563eabab7fecf43dba790`, `updatedAt`
`2026-09-26T04:01:00Z`. Reproduced verbatim.

```text
#### Summary

This implements the straggler profiler for the No.11 task: **implemented, not planned** and **default-off** (`RELAX_STRAGGLER_ENABLE` unset leaves `config.timers` upstream). It observes only and adds **no telemetry collective on the training path**. Three differentiators: (1) **no training-path collective** — ranks ship envelopes out of band to a rank-0 TCP collector while the training thread records only a host timestamp and, when CUDA is available, one event; (2) a **bounded, failure-isolated observer** with constant caps, counted drops and a terminal `active → degraded → disabled` state machine; (3) **topology-aware equivalent cohorts**, compared only within a `(topology_epoch, stage_schema, tp, pp, vpp, chunk, cp, ep, etp)` class along the data-parallel axis (EP/ETP/EDP are not compared). Each is pinned by a test, and they do **not** imply full stage coverage: before `08184e6` the enclosing `forward-backward` interval was dropped as `late` and never judged. Attention and MoE stay schema-only. The long-form design lives in RFC #357. Acceptance is **PARTIAL on all three official criteria** — see Verification.

#### Changes

- **Timer shim (`megatron_timer_shim.py`).** Drop-in `config.timers`: one host timestamp plus, when device timing is available, one CUDA event per call on the current stream. Never reads back, never synchronises, counts suppressed `barrier=True` calls.
- **Observer (`observer.py`).** Off-thread readout: a preallocated CUDA-event pool, a bounded pending deque and one daemon thread. The wire sequence is stamped at interval **completion**, so an enclosing nested timer is not dropped as out-of-order; pool exhaustion degrades to host-only.
- **Collector (`collector.py`, `runtime.py`).** Out-of-band rank-0 TCP: rank 0 ingests while other ranks send from a bounded queue; packets are validated and deduped on `(run_id, topology_epoch, global_rank, sample_seq)`; malformed / duplicate / late packets are counted, not judged.
- **Detector (`detector.py`).** `facts` and `candidate_causes` are separate, default `undetermined`. Windows are bounded **time** windows (default 5 s); comparability is **tokens alone**, **per rank**, against the peer median (`work_tolerance` 0.05); `sequences_delta` / `microbatches_delta` are evidence-only, and per-window workload is the median of per-sample readings so arrival order cannot flip a verdict.
- **Reporting (`reporter.py`, `utils/training/train_metric_utils.py`).** `log_perf_data_raw` merges `perf/straggler/*` into the **already-made** perf dict via `log_dict.update(...)` before the single existing platform write; `coverage` comes only from an explicit cohort ratio, the old fallback now `judged_fraction`.

Fix commits since the previously-cited `5ed640c`, oldest first; current head is `ce9b637`:

| commit | fix |
| --- | --- |
| `6293d3b` | `ray-job.sh` warn-only probe for a live Ray job behind a free GPU lock. |
| `acfafb2` | Judge workload **per rank** and aggregate order-independently; fixes the pair-wide gate that let an over-worked peer withhold an equal-work straggler, the last-arrival-wins workload, and the counter contradictions. |
| `18c8a95` | In-rollout-only step context (`global_step` optional, monotonic `step_ordinal` added); surface publish/gate counters; correct `coverage` vs `judged_fraction` and `dropped`; mark the PP>1 exporting rank. |
| `08184e6` | Stamp the interval sequence at completion so nested timers are judged, with a regression test driving the real shim/observer/collector. |
| `d3ca9e3` | Ruff format on the reporter tests. |
| `ce9b637` | Ruff + docformatter on the audited files. |

Commit attribution is honest: concurrent agents in one worktree let a `git add -A` sweep some changes into another agent's commit, so commit granularity does not perfectly map to authorship; history was deliberately not rewritten.

#### Verification

Measured at head `ce9b637`:

- **Straggler suite:** `347 passed, 2 skipped, 14 warnings in 48.35s` (`pytest tests/utils/straggler -q`). Both skips are the legitimate "requires the relaxed training stack (Megatron + transfer_queue)" class with explicit reasons, not skip-as-a-fix.
- **Full repository suite — honest statement.** It cannot be run cleanly here; it aborts on missing optional deps. With `--continue-on-collection-errors` it is `65 failed, 2358 passed, 401 skipped, 8 errors`, and **zero** of those failures are attributable to this work (`transfer_queue`, `pylatexenc`, `diffusers`, `audioread`, `megatron` missing, plus the environment-gated `tests/backends/megatron/test_gdn_cp_gpu.py`). No clean full-suite pass is claimed.
- **Fixes verified by tests (E1, E4, E10, E8, E3).** The nested-timer regression (`test_straggler_nested_timers.py`) asserts zero late packets, all packets judged, and a `host_only_stall` verdict on the enclosing `forward-backward` interval (pre-fix: `late_packets=16`, zero straggler verdicts); the 100/100/100/300 ms, tokens 1000/1200/1000/1000 case judges rank 3 with `tokens_delta=0.0`; either arrival order gives identical facts; malformed samples no longer inflate `uncertain_judgements`; `coverage` now comes only from an explicit cohort ratio (fallback `judged_fraction`); and `dropped` sums every detector eviction counter, including `sample_evictions`.
- **Overhead (criterion 1) — PARTIAL, not yet demonstrated.** A single-session point estimate exists: `step_time` median −0.118 % (0.9262 s vs 0.9251 s, OFF vs ON) and mean +2.558 % (1.9208 s vs 1.9699 s), the mean driven by a startup tail. Whole-run wall clock, throughput, p50/p95/p99 and a startup-versus-steady-state split were **not captured**, so the criterion is not demonstrated; the mean is not dismissed as an outlier and acceptance is not announced on the median alone. Design bounds and microbenchmarks are never acceptance evidence.
- **Accuracy / loss / overlap (criterion 2) — PARTIAL.** No loss or overlap evidence exists; the change is additive and adds no training-path collective, but that is design evidence only.
- **Reporting (criterion 3) — PARTIAL.** Platform reporting is at **rollout cadence**, primary rank only, and rides the existing path: `report_once` returns `perf/straggler/*` and `log_perf_data_raw` merges them into the same dict the pre-existing platform write already sends — no new HTTP request or collective, and the merge is failure-isolated. Nuance: the `perf <rollout_id>` INFO line is emitted **before** the merge, so it does not contain the straggler keys; they reach the platform metric record through the existing write. The collector's summary and status JSON are **log and file evidence, not platform metrics**; diagnosis is near-real-time (default 5 s window) while export is rollout-cadence, the hop latencies were measured in-process on the real components with a fake device backend (20 000 iterations, three runs): completion to ingest p50 **20.3 us** (p99 35.5 us); last-envelope to verdict p50 **52.1 us** when triggered and **36.7 us** on flush; `report_once` p50 **34.5 us** populated, **24.7 us** empty, **83.5 us** with INFO logging, **0.75 us** disabled; a start/stop pair costs a paired p50 delta of **7.9 us** over a no-op control (**23.4 us** with inline local ingest). Structurally, ingesting a window's last envelope produced **no verdict in 4 000/4 000 iterations** - a verdict needs a later envelope beyond `WINDOW_GRACE` or a `flush()`. These are CPU proxies, **not** GPU measurements, and MetricsService was deliberately **not** used because its only client blocks on HTTP from the training thread. Under `pp_size > 1` the collector-versus-export rank mismatch is a stated limitation, marked by `collector_status_available`.
- **Prior counts are not reusable.** The earlier recorded ON run (1403 persisted envelopes, all one microbatch and eight sequences, 57 `workload_incomparable` windows, 253 uncertain verdicts, zero stragglers) is **NOT reusable evidence**: its counts are unit-contaminated by the old summed-work rule and the archived run never exercised the repack branch because `max_k == 1` throughout.
- **Documentation-versus-behaviour contradictions (measured, recorded not fixed):** `reporter.py` claims it never blocks the training thread and performs no I/O, yet with INFO logging it writes three lines synchronously (p50 34.5 -> 83.5 us); `report_once`'s "enabled but no runtime" branch is unreachable through the public API, so the `collector_status_available=0` marker comes from the collector-ownership check, not that branch; the timer shim says start/stop only record a timestamp and optionally a CUDA event, yet on the no-CUDA path `stop()` also builds the envelope and calls the consumer inline; the observer's "nothing may block on the training thread" is loose on the host-only path.
- **REAL-GPU CORRECTION (2026-09-26, first fresh paired session at `ce9b637`).** The completion-order change (`08184e6`) is NOT sufficient on real hardware and its "FIXED" status is downgraded. In a 48-step DP4 ON run the collector reports `envelopes=2069 judged=1455 invalid=0 duplicate=0 late=614` - **29.7% of every envelope is discarded as `late`** - and the enclosing `forward-backward` interval was judged **0 times**, while the level-2 timers beneath it (`forward-compute`, `backward-compute`, plus communication and optimizer stages: 9 distinct raw names) were judged normally. So the phase-wrapper stall the fix was meant to expose is still invisible, and the CPU-harness result does not transfer. Coarse-stage presentation is nevertheless confirmed live on hardware: real verdicts are emitted as `straggler stage: name=params-all-gather coarse_stage=communication`, carrying both the raw timer name and the coarse group. The cause is now identified from the persisted envelopes: in real Megatron the per-step completion order places `forward-compute` in slot 1 and `backward-compute` in slot 2, but the enclosing `forward-backward` interval completes in slot 7 - **not last** (`params-all-gather` takes slot 11) - and `forward-backward` loses 18 of 48 instances per rank (30, 30, 32 and 41 of 48 across the four ranks), while `optimizer-inner-step` loses 4. The dedup layer declares any envelope whose sequence is below the newest already seen for that rank to be `late` (631 of 2112 here, with `invalid=0 duplicate=0`), which is only sound when arrival order equals completion order. It does not: several intervals per rank are in flight at once, the long level-1 interval is built and delivered after shorter, higher-sequence intervals from the same step, and it is then discarded as `late`. A phase-level coverage claim is therefore withdrawn for this build. The CPU harness passes only because its delivery is strictly ordered, so the completion-order change alone was never the whole fix; the dedup ordering rule itself has to change. A blanket in-flight tolerance was implemented and then **refuted by the existing suite**: relaxing the ``seq < newest`` comparison to ``seq < newest - tolerance`` accepts the real-GPU ordering but breaks 7 pre-existing tests, including the red-team conservation test and the per-rank ordering and packet-class conservation tests, because those pin the strict contract deliberately. The change was therefore reverted and the tree is back at ``ce9b637`` with 347 passed and 2 skipped. The defect is in the observer's delivery order, not in the dedup rule, and this is now pinned to a line: `_readout_until_stopped` pops `_pending` in completion order, and when `_process` reports that an interval is not yet readable it re-queues the token with `self._pending.append(token)` - **at the tail**. A deferred token is therefore delivered after every later, higher-sequence token, so the collector sees a sequence regression and drops it as late. That is exactly the observed shape: the longest interval, `forward-backward` in slot 7, is the one most likely to need a retry and loses 18 of 48 instances, `optimizer-inner-step` in slot 9 loses 4, and the short intervals in slots 1, 2 and 11 lose none. The CPU harness cannot show this because nothing there is ever deferred, so its delivery stays strictly ordered. The fix therefore belongs in the readout loop, which must preserve sequence order under retry without allowing head-of-line blocking, and the strict late contract - and with it all seven pre-existing tests - can then stand unchanged. No test was weakened or removed.

First fresh paired session (same commit, GPU set, recipe, seed and step count; only `RELAX_STRAGGLER_ENABLE` differs; 48 optimizer steps each, processed fresh): `perf/train_time` OFF median 15.8572 s vs ON 15.8753 s, paired median delta **-0.028%** and paired mean delta **-1.402%** (max |delta| 4.83 s); `perf/actor_train_time` paired median delta **-0.048%** and paired mean delta **-2.008%**. One session only: no session-aware interval is computable, whole-run wall clock, throughput, p50/p95/p99 and the startup/steady-state split were not captured, and both arms ran under a machine load near 50 with about 35 s per step against 6.5 s per step in the archived arms, so this pair is internally consistent but not comparable with the archived sessions. Criterion 1 remains **PARTIAL / not yet demonstrated**.

**Known limits (itemised, not vague future work):** (1) dedup `_newest` has no TTL, so a restarted observer under a stable `run_id` is still blacklisted as `late`; (2) `MAX_SAMPLES_PER_RANK` can drop a late slow tail (counted, cap deliberately unchanged); (3) `peer_median_ms` includes the rank itself (evidence mislabel; detection uses the minimum); (4) the floor gate is a systematic false negative — the gap must exceed both 5 % of the fastest peer and 5 ms, so a 10× slowdown on a 0.4 ms stage is invisible; (5) `cohort_below_min_size` is unreachable at the default `min_cohort_size=2`; (6) a packet delayed more than two windows is lost (`WINDOW_GRACE=1`); (7) the workload stamp is taken after the interval closed; (8) the no-CUDA path detects on the training thread and the collector logs under its state lock; (9) `RELAX_STRAGGLER_TOPOLOGY_EPOCH` is inert; (10) no rollout/topology reset, so a stall drains into the next rollout's perf log; (11) `protocol.validate()` never inspects `host_start`, so a far-future value can force-close pending windows.
- GitHub checks: none reported on the current Draft PR / fork head.

#### Risk & Rollback

- **Default-off and cheap.** With `RELAX_STRAGGLER_ENABLE` unset, both training `config.timers` sites stay upstream, so a disabled profiler costs one cached enablement boolean and no partition work.
- **Bounded and failure-isolated.** Every observer structure has a constant cap and a drop counter; `disabled` is terminal; failures across the profiler are counted and swallowed and cannot reach `train` / `train_one_step` / the optimizer. Missing observations are omitted, not zero-filled.
- **Known limitation — collector/export rank mismatch.** Under `pp_size > 1` the collector is on global rank 0 while the platform merge runs on the Megatron primary rank; those ranks differ, so the exporting rank now emits `collector_status_available=0` instead of silently exporting nothing. The mismatch is **not** claimed fixed.
- **Rollback.** Revert the commits, or leave the feature disabled by unsetting `RELAX_STRAGGLER_ENABLE`.

#### Checklist

- [x] Diff contains only changes necessary for this task
- [x] New / related tests pass at head `ce9b637` (`tests/utils/straggler`: 347 passed, 2 skipped; both skips are explicit training-stack skips)
- [ ] Docs / scripts / defaults updated — scripts and defaults are; no bilingual `docs/en` + `docs/zh` page was added, so this item is left unticked
- [x] No secrets, datasets, checkpoints, or machine-private info
- [ ] Review comments addressed one by one (none yet — Draft PR)
- [ ] CI passing (no checks are reported on this Draft PR / fork head)






```

## Exact final rereview comment

**There is no rereview comment to reproduce.** I checked the public object three
ways and all returned empty:

- `gh api repos/redai-studio/Relax/issues/378/comments` → empty
- `gh api repos/redai-studio/Relax/pulls/378/comments` → empty
- `gh api repos/redai-studio/Relax/pulls/378/reviews` → empty

This is consistent with the PR body's own checklist: "Review comments addressed
one by one (none yet — Draft PR)". Because no rereview comment exists, this
section is stated as empty rather than fabricated. Nothing here is quoted from
any other team's PR or issue.

---

```text
CODE_BLOCKERS = The cac4cb6 readout-order fix (relax/utils/straggler/observer.py, +test_straggler_readout_order.py) is committed and the 350-pass suite is green, but it has NOT been re-verified on real GPU; the ce9b637 build it replaces discarded 631 of 2112 envelopes (29.7%) as late and judged the enclosing forward-backward interval 0 times (RFC #357 / PR #378 REAL-GPU CORRECTION). Documented known limits E2, E3-cap, E5, E6, E7, E9, E11, E12, S1, S2, S3 and the four doc-vs-behaviour contradictions remain unfixed by design.
ACCEPTANCE_BLOCKERS = Criterion 1: live campaign gpu_campaign/abba-cac4cb6 has 0 completed arms (1 arm dir, no manifest.json, 3 of 48 perf lines) against the >=6 required fresh paired AB/BA sessions. Criterion 2: no loss/grad-norm/accuracy and no compute-communication overlap measurement exists (all arm summaries carry "train_metrics": {}). Criterion 3: no real-GPU sample-to-platform-visible reporting latency exists (only CPU proxies with a fake device backend).
DOC_BLOCKERS = RFC #357 and PR #378 live bodies are stale: they name ce9b637 as the freeze/head and "347 passed, 2 skipped" and state the readout-order fix was reverted, while the pushed head is cac4cb6 with "350 passed, 2 skipped". The checked-out /root/autodl-tmp/relax-work/RFC357_C2_FINAL.md is an older revision naming HEAD 47581e0. The working tree became dirty during the report session with uncommitted docs changes not made by this report (M docs/.vitepress/config.mts, ?? docs/en/guide/straggler-profiler.md, ?? docs/zh/guide/straggler-profiler.md), so the documented "working tree clean" freeze condition is violated at report time and no docs revision is pinned. Four documentation-versus-behaviour contradictions remain: reporter.py's "never blocks / no I/O" claim vs synchronous INFO logging (p50 34.5 -> 83.5 us); report_once's unreachable "enabled but no runtime" branch; the shim's no-CUDA-path inline envelope build/consumer call; the observer's loose "nothing may block on the training thread" on the host-only path.
EXTERNAL_BLOCKERS = GPU window and machine load (the pair ran at ~32.4 s/step vs ~6.5 s/step for the archived arms, under load near 50 per the PR/RFC body); the acceptance campaign is still in progress; the PR is a Draft with zero CI checks reported (statusCheckRollup = []) and reviewDecision = REVIEW_REQUIRED, so no independent review exists.
ACCEPTANCE_1 = PARTIAL
ACCEPTANCE_2 = PARTIAL
ACCEPTANCE_3 = PARTIAL
READY_FOR_REREVIEW = NO
```

## Appendix Z — 2026-09-26 evening closeout addendum

**Environment**: a machine-level fault was isolated and confirmed this evening
(any Ray worker that initializes CUDA dies in 5–17 s; minimal reproducer and
the full elimination matrix in
`env_incident_20260926_evening/INCIDENT_REPORT.md`). GPU-dependent acceptance
work is ENV_BLOCKED until the §6 re-entry test (m1 reproducer + canary7) passes.
Cluster state at handoff: head node up (training-venv interpreter verified),
Serve applications shut down, zero `/dev/nvidia*` fd holders, GPUs idle.

**Product code**: unchanged and still frozen at `cac4cb6` (worktree clean; the
diagnostic instrumentation lives only on branch `diag/task11-stacktrace`,
commit `d04e07f`, worktree `task11-diag` — never to be merged).

**Status deltas vs the body above**:
- C1 remains at one valid pair (`abba-cac4cb6-run4` S1); the planned ≥6-pair
  campaign could not start (ENV_BLOCKED). C1 = NOT PASS / INCOMPLETE stands.
- The interpreter root cause from the prior handover is fixed and verified
  (workers run the training venv); it was necessary but not sufficient — the
  CUDA-in-Ray-worker fault dominates.
- Ray cluster recovery procedure that works in this container:
  `/root/autodl-tmp/megatron-stack/venv/bin/python /tmp/opencode/ray_venv_launcher.py start --head --port=6379 --dashboard-host=127.0.0.1`
  (the venv has no `bin/ray` and no `ray.__main__`; the entry-point metadata
  route via `ray.scripts.scripts:main` is required).

## Appendix Y — 2026-09-26 late-night closeout addendum (final)

**Public text**: the `+0.192 %, not +0.192 %` typo in the machine-recomputed
footnote of RFC #357 / PR #378 is resolved by deleting the footnote entirely
(the bodies already carry the correct `+0.192 %` figure in every position).

**GitHub CI triage (B17)** — both failures were test-file defects, not product:

| Workflow | Root cause | Class | Fix |
| --- | --- | --- | --- |
| CI (Python 3.10–3.12) | `test_straggler_workload_publish_runtime.py` collection error on runners that ship `transfer_queue` but no Megatron: the `transfer_queue` importorskip guard did not cover the actor import chain | CI_INFRA (missing optional-dep guard) | `d7b0050`: explicit `pytest.importorskip("megatron")` |
| GPU Unit (H20) | `test_straggler_pickle_boundary.py` crashed with `TypeError: Path(None)`: distribution-installed Megatron is a namespace package (`__file__` is None) | CI_INFRA (namespace-package handling) | `d7b0050`: `_megatron_root` derives candidate roots from `__path__` |

Verified both ways: full pass under the training venv (11 passed), clean skips
under the CPU venv (5 passed, 2 skipped). The straggler suite on the new head:
**350 passed / 2 skipped** — identical to the frozen baseline; product freeze
intact.

**Docs (B18)**: bilingual user guide + sidebar committed as `f3403b0`
(docs-only; privacy scan clean; env-var table cross-checked against
`relax/utils/env.py`).

**Evidence (B21)**: immutable evidence branch established:
`evidence/task11-straggler` @ `bd6297f` (campaign arms valid+invalid, frozen
protocols, estimator, counter audits, latency report, environment incident,
fingerprint snapshot, staged docs sources).

**GPU re-entry gate (B4)**: executed 2026-09-26 22:58–23:02 —
Step 1 (out-of-Ray CUDA canary, 150 s): PASS; Step 2 (m1 Ray-worker CUDA
reproducer): FAIL twice (`WorkerCrashedError` ~3 s after `set_device`).
The machine-level fault is still active → `GPU_ENV_READY = NO`; the campaign,
C2 traces and C3 live measurement remain ENV_BLOCKED per protocol. No further
GPU attempts until Step 2 passes.

**Heads**: product `cac4cb6` (freeze) → `d7b0050` (test-only) → `f3403b0`
(docs-only). PR #378 Draft, mergeable; both this PR and PR #370 await
maintainer fork-workflow approval for their current heads' CI runs.
