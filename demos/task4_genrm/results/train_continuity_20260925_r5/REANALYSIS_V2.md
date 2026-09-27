# Train-continuity r5 — three-timeline re-analysis, v2 (2026-09-27)

Supersedes `REANALYSIS_THREE_TIMELINES.md` (v1). v2 differences, from review:
explicit inputs and timezone basis (`--log/--events/--out/--date/--tz-hours`,
unit-tested incl. cross-midnight and window boundaries); step START vs
EXECUTION END vs ACTUAL OPTIMIZER UPDATE separated; the three scale windows
analysed individually; reward evidence split into columns; sample integrity by
unique rollout IDs. v1's merged step/rollout bound, its "raw_reward all zero"
reading (based on one rollout's line — rollouts 2 and 4 are in fact non-zero)
and its unscaled error count are corrected here; v1 is retained unchanged
below it for the revision history.

Inputs: `raw_job_driver.log` (archived here; sha256
`e0fd4db7c6676974dd29815f67594702e70c74b35e679925d29cfa9d6a03f10c` — see
`raw_job_driver.log.sha256`) and the monitor's `events.json`. Epoch basis:
local CST (tz +8) verified against `events.json` (`monitor_start` epoch
1790352563.7 == 00:09:23.7 CST).

## 1. Three step timelines (raw log, ANSI-stripped, timestamped lines only)

| Timeline | Marker | Result | Max gap |
| --- | --- | --- | --- |
| Step start | `Actor training step N/8` | **8/8** (ids 0–7) | 75.0 s |
| Step execution end | `Actor training completed step N/8` | **8/8** (ids 0–7) | **29.0 s** |
| Optimizer / weight updates | `Update weights: Nit` / `Weights updated for …` | **15 events** | 58.0 s |
| Rollout completion | `Rollout fully completed for rollout_id: N` | **8/8** (ids 0–7) | 76.0 s |

A start line alone proves nothing about completion; the **execution-end** line
is the completion marker, and its 29 s worst gap is the honest continuity
bound for the actor loop. The 15 weight-update events are the serving-side
sync chain (Slim `Update weights` + `Weights updated for actor_fwd_ref`);
their continuation through all windows is the pre-existing weight-sync path
the criterion asks to keep healthy.

## 2. The three scale windows, separately

| Window | Span (duration) | Step starts inside | Step ends inside | Rollouts done inside | Judge batches (engine) | Error lines |
| --- | --- | --- | --- | --- | --- | --- |
| scale-out execution | submit → ACTIVE (58.8 s) | – | – | – | 1 (elastic, its boot warmup) | 1 (INFO scale-registry line containing the word "error" in a field) |
| **dual-replica stable** | ACTIVE → scale-in submit (45.2 s) | 1, 2 | 0, 1 | 1 | **1 (initial) + 1 (elastic)** | **0** |
| scale-in execution | submit → COMPLETED (1.0 s) | – | – | – | – | 1 (registry INFO) |

The stable window contains one full step boundary, one rollout completion and
**zero error lines**. No timeline's maximum gap spans a window boundary.

## 3. Reward evidence, split into columns

| Column | Evidence | Value |
| --- | --- | --- |
| Judge inference traffic | GenRMEngine prefill/decode batches in the log | initial engine 22, elastic engine 2 (1 boot warmup + **1 in the stable window**) |
| Per-rollout reward metrics | `rollout/raw_reward` in each rollout metric dict | present for **8/8 rollouts**: 0.0, 0.0, **0.125**, 0.0, **0.25**, 0.0, 0.0, 0.0 |
| Judge errors | GenRMEngine lines matching error/exception/traceback | **0** |
| Format-check short-circuit | not individually logged in this recipe | not observable from this log; bounded below |
| Elastic attribution | inference batches on the elastic engine pid inside the stable window + the monitor's `served=1` counter tick | **exactly one request** |

Bounded claim (per review): `raw_reward` values, the absence of exceptions and
the `served` counter each alone prove nothing about per-request judge success.
What this log supports is the conjunction — judge inference traffic observed on
both engines, reward metrics computed for every rollout with non-zero values on
rollouts 2 and 4, and zero judge error lines. Replica-level scoring correctness
and parse-gate independence are proven separately by the engine-attribution
consistency runs (r3 @ `945741e`, r6 @ `0481701`: 800 attributed replies,
independent parse gate, zero truncation).

## 4. Sample integrity (unique IDs against the expected set)

`Saved rollout result (8 samples) to …/rollout_result/train/{N}.jsonl` for
N = 0…7, each exactly once: **64/64 samples, no missing and no duplicate
rollout IDs** (carry-over windows all report `aborted=0`, `deficit=0`,
`surplus=0`). The per-sample JSONL files themselves were rotated away on the
runner; the archived log (sha256 above) and these lines are the durable
record — a future rerun should preserve the files.

## 5. Log error classification (all lines matching error/exception/failed/traceback)

| Class | Count | Assessment |
| --- | --- | --- |
| `RewardWorker` TemporaryActor creation failures (`ModuleNotFoundError: pylatexenc`) | 36 message pairs across the run | pre-existing optional-dependency gap in a worker class this recipe does not use (the judge is GenRM); did not block training |
| Ray GCS `Failed to kill actor` | ~7 | GCS cleanup attempts on those dead RewardWorkers; scale-op churn noise, not a scale-path failure |
| `flash_attn_3 failed to import` fallback | 5 | benign |
| checkpoint healthcheck/inspect warnings | 2 | boot-time, transient |
| ServeController teardown retries | 2 | shutdown-time, expected |
| sglang router `register_tokenizer` WARN | 1 | benign |
| Judge (GenRMEngine) errors | **0** | — |
| Errors inside the dual-replica stable window | **0** | — |

## 6. Verdict (re-judged from existing raw data; no GPU rerun needed)

- **Criterion ⑤ (training continuity): PASS** — 8/8 step starts AND 8/8
  execution-ends AND 8/8 rollout completions AND 15 weight-update events, with
  the execution-end worst gap at 29 s and no gap spanning any scale window;
  zero error lines in the dual-replica stable window; 64/64 samples by unique
  rollout IDs.
- **Elastic contribution during continuity: one inference batch in the stable
  window** (plus its boot warmup), cross-checked against the `served=1`
  counter tick — recorded as the bounded statement; replica correctness rests
  on the criterion-② attribution runs, not on this traffic share.
