# Train-continuity r5 — three-timeline re-analysis (2026-09-27)

Answers the review finding that the r5 driver (a) merged optimizer steps and rollout lines
into one stall bound, (b) counted rollout start *and* completion log lines, and (c) relied on
`served > 0` (incremented in `finally`) as the elastic-replica contribution proof. This
re-analysis uses the RAW ray job driver log
(`job-driver-raysubmit_qT4vVNVyiMub3sur.log`, preserved here) plus the monitor's engine
snapshot series — not the driver's merged verdicts.

Run: `train_continuity_20260925_r5` (job started 2026-09-26 00:09:44; monitor t0).
Scale window: scale-out ACTIVE at t=248.7 s, scale-in submitted at t=293.9 s (45.2 s of
capacity-2 operation).

## 1. Three separate timelines (raw log, completion lines only)

| Timeline | Source line | Result | Max gap |
| --- | --- | --- | --- |
| Optimizer steps | `Actor training step N` | **8/8** (ids 0–7, each exactly once) | **75.0 s** |
| Rollout completions | `Rollout fully completed for rollout_id: N` | **8/8** (ids 0–7, each exactly once) | **76.0 s** |
| Reward returns | per-rollout metric dict carrying `rollout/raw_reward` | **8/8** rollouts carry computed reward values | (per-rollout; bounded by the rollout gaps) |

- The maximum gap of **neither** timeline spans the scale window (the driver's merged
  bound could previously mask an actor stall behind rollout chatter; separated, both
  bounds hold independently).
- Sample-count verification: `Saved rollout result (8 samples)` appears exactly 8 times →
  **64/64 samples landed**; every carry-over window reports
  `committed_current=4 next_step_deficit=0 oversample_surplus=0 aborted=0`
  (verified by direct grep over all 8 lines — zero deficits, zero surpluses, zero aborts).
- `All rollouts finished` and `All training steps finished` both present.

## 2. Reward values (honest reading)

Every rollout's metric dict carries `rollout/raw_reward: 0.0` with
`rollout/response_len` constant at 2048 (max length) — i.e. the judge scored truncated
max-length generations as wrong, uniformly. Zero reward-call errors/retries are logged
during the run; reward computation happened on every rollout. The reward *values* being 0
is a property of this continuity recipe (0.6B judge, truncated 2048-len responses), not a
reward-path failure; replica agreement and parse-gated successful attribution of the judge
itself are proven separately by the `reward_consistency` runs (800 engine-attributed
replies, r3 at `945741e` / r6 at `0481701`).

## 3. Elastic-replica contribution — thin, and now stated as such

The monitor's `/engines` snapshots show the elastic engine (`172.17.0.2:16001`) at
`served=0, inflight=1` at t=293.1 s and the driver's direct check at t=293.8 s reading
`served=1`: **exactly one request completed on the elastic replica inside the 45.2 s
scaled window** (the initial engine's counter rose 0→11 across the whole run). The
counter increments in a `finally` block, so it counts completed handling including
failures; with `aborted=0` in all carry-over windows and no error lines in the window,
the request is consistent with success, but one counter tick is **not** per-request
success attribution. The elastic replica's ability to compute correct rewards is proven
by the engine-attribution consistency runs, not by this continuity run's traffic share.

## 4. Log error classification (all lines matching error/exception/failed/traceback)

| Class | Count | Verdict |
| --- | --- | --- |
| `RewardWorker` creation-task import failures (`ModuleNotFoundError: pylatexenc`, a missing optional dep of the training venv) | 36 deduped messages, 72 distinct TemporaryActor pids (34 at startup + background Ray retries throughout) | Pre-existing environment gap on a worker class this recipe does not use (the judge is GenRM); unrelated to this PR's diff; did not block training |
| `flash_attn_3 failed to import … Falling back to native attention` | 4 | benign fallback warning |
| `[MetricsClient] health_check failed: HTTP 404` | 1 | benign platform health-probe miss |
| argparse type-inference warnings | 2 | benign |

**Zero exceptions during the 45.2 s scaled window.**

## 5. Re-verdict

- **Criterion ⑤ (training continuity): PASS, now on separated three-timeline evidence**
  (8/8 steps and 8/8 rollouts with 64/64 samples, zero aborts/deficits, max gaps 75–76 s
  not spanning the scale window, zero in-window exceptions) — strictly stronger than the
  original merged assertion.
- **Elastic contribution during continuity: one counter-attributed request** — recorded
  as a bounded statement; the replica-correctness claim rests on the attribution runs of
  criterion ②, not on this traffic share.
