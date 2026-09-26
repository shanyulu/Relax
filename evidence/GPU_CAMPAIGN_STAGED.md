# Task 11 — GPU campaign, PRE-STAGED (deferred, not cancelled)

**Status: DEFERRED — GPU temporarily withdrawn by owner; the campaign resumes
when the window returns.** Nothing in this file has been executed. It is staged
so the window's first minute is spent launching, not diagnosing. No substitute
evidence (CPU extrapolation, microbenchmark-as-overhead, or an earlier arm) is
offered for any item here.

## 0. Evidence boundary you must not blur

| class | commit | meaning |
| --- | --- | --- |
| real-machine-verified | `22e9776` (+ ancestors) | job `raysubmit_VdVuc8JXUAjimzXz`, 48/48 steps, exit 0, 1399 persisted envelopes, `measurement_kind=device` |
| CPU-tested only | `47581e0` (+ later CPU commits) | producer + comparability gate; **no experiment claimed** |

The workload producer landed **after** `22e9776` and changes the training path,
so **every arm below measures producer-era code**. At campaign start, freeze the
tip and use the *same* commit for every arm:

```bash
export CAMPAIGN_SHA=$(git -C /root/autodl-tmp/relax-work/task11-c2 rev-parse HEAD)
git -C /root/autodl-tmp/relax-work/task11-c2 status --porcelain   # must be empty
```

`22e9776` stays the last measured commit; it is **not** the code these arms
measure. Do not cite `22e9776`'s numbers as results for the producer-era code.

## 1. Preconditions (every launch)

```bash
# One GPU job at a time, always.
exec 9>/root/autodl-tmp/relax-ray-gpu.lock && flock -n 9 || { echo LEASE-BUSY; exit 1; }
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader
source /root/autodl-tmp/relax-work/task11_evidence/gpu_campaign/env.sh   # sets no_proxy/NO_PROXY
# env.sh deliberately does NOT export RAY_ADDRESS or PROMPT_SET.
```

Ray head must be up at `172.17.0.2:6379` with `no_proxy` exported in the head's
environment; the previous attempt died with `Could not find any running Ray
instance` and `MASTER_ADDR=`, so **verify the head before submitting**:

```bash
ray list nodes --format json | jq -r 'map(select(.state=="ALIVE"))|length'   # >0
```

Per-arm tree state is mandatory (`CLEAN@<sha>` or `DIRTY-TREE@<diffsha>`), with
dirty diffs saved to `gpu_campaign/dirty_tree_<arm>.patch`, and never two
revisions inside one block.

## 2. Arm list (in execution order)

| # | block | arms | recipe / driver | exit criterion it moves |
| --- | --- | --- | --- | --- |
| 1 | healthy ON re-run, producer live | 1 ON | `scripts/training/sft/run-qwen3-0.6B-4xgpu-dp4-observer.sh` | producer publishes per-rank tokens; FPR re-measured; criterion 3 |
| 2 | AB/BA overhead | 6 sessions × (A=off, B=on) | `task11_evidence/run_abba_sessions.py` | overhead < 0.5 % (official 1) |
| 3 | fault isolation | A–E | `gpu_campaign/downgrade_harness.py` + real job | failures never escape (official 2) |
| 4 | TP2×DP2 cohort correctness | 1 | `run-qwen3-0.6B-4xgpu-tp2dp2-observer.sh` | topology-equivalent cohorts |
| 5 | PP2×DP2 | 1 | `run-qwen3-0.6B-4xgpu-pp2dp2-observer.sh` (droppable) | no cross-stage comparison |
| 6 | sensitivity +5/+10/+20/+50/+100 % | 5 | injected SM-carve-out recipe | TPR/FPR characterisation |
| 7 | overlap trace | 1 ON + 1 OFF | `torch.profiler` recipe | instrumentation does not serialise overlap |
| 8 | reporting latency | 1 ON | existing recipe, timestamps only | platform metrics latency |

## 3. Exact launch command (block 1, the first thing to run)

```bash
cd /root/autodl-tmp/relax-work/task11-c2
source /root/autodl-tmp/relax-work/task11_evidence/gpu_campaign/env.sh
export WORKING_DIR=/root/autodl-tmp/relax-work/task11-c2
export EXP_NAME=qwen3-0.6b-sft-dp4-on-producer
OUT="$CAMPAIGN/on-smoke-producer"; mkdir -p "$OUT/straggler"
git status --porcelain > "$OUT/tree-status.txt"; git rev-parse HEAD > "$OUT/head.sha"
export RELAX_STRAGGLER_ENABLE=1 \
       RELAX_STRAGGLER_COLLECTOR_ADDR=127.0.0.1:29763 \
       RELAX_STRAGGLER_OUTPUT_DIR="$OUT/straggler" \
       RELAX_STRAGGLER_WINDOW_S=5.0 RELAX_STRAGGLER_WARMUP_WINDOWS=2 \
       RELAX_STRAGGLER_REPORT_INTERVAL_S=10.0
NUM_ROLLOUT=48 SAVE=0 bash scripts/entrypoint/ray-job.sh \
  scripts/training/sft/run-qwen3-0.6B-4xgpu-dp4-observer.sh 2>&1 | tee "$OUT/submit.log"
```

Only these six `RELAX_STRAGGLER_*` names are forwarded by the recipe into
`RUNTIME_ENV_JSON`; injection/topology knobs are **not** forwarded and need a
recipe edit if a block requires them.

## 4. Per-arm manifest fields (mandatory; this is what makes a comparison unconfounded)

Every arm writes a manifest JSON with at least:

```json
{
  "arm": "S1-off", "commit": "<sha>", "tree_state": "CLEAN@<sha>",
  "recipe": "...", "num_rollout": 48, "window_s": 5.0,
  "exit_code": 0, "first_step_seen": true, "steps_completed": 48,
  "workload_present": true,
  "per_rank_tokens": {"0": 12345, "1": 12301, "2": 12388, "3": 12340},
  "per_rank_sequences": {"0": 8, "1": 8, "2": 8, "3": 8},
  "per_rank_token_delta_pct": {"0": -0.3, "1": -0.7, "2": 0.1, "3": -0.4},
  "carrier_balanced": true,
  "envelopes_ingested": 0, "envelopes_persisted": 0,
  "verdict_kinds": {}, "workload_incomparable_windows": 0,
  "truncated_tail": 0, "malformed": 0,
  "overhead_ready": true, "invalid_reason": null
}
```

`per_rank_tokens` comes from the new producer (`workload.tokens` per rank), and
is the field that finally answers the across-rank work question. An ON arm with
zero envelopes, or with `workload_present: false`, is `valid: false` and must not
be paired.

## 5. Carrier balance check (run before any AB/BA pairing)

The `rollout/total_lengths/max` vs `/min` line is **one rank's within-rank spread
over its 8 local samples** — it is not an across-rank comparison, and that rank's
own mean swings −12.3 % … +22.5 % across 48 steps. So balance must be *measured*:

1. Inspect `--balance-data` behaviour in the recipe and confirm it balances the
   **per-step local token sum**, not merely the sample count.
2. From block 1's manifests, compare `per_rank_tokens` per step. `carrier_balanced`
   is true only if every rank is within ±1 % of the peer median on every step.
3. If the carrier is not balanced, the detector will (correctly) report
   `workload_incomparable` windows rather than stragglers, and the overhead
   comparison must either use a balanced carrier or declare the residual
   imbalance as a named confound. **Never** pair arms whose manifests disagree on
   balance.

## 6. Frozen estimator (do not modify)

`analyze_overhead.py`, sha256
`2d93332c9c59f68c8f4be7ac3add0386499fc8a8d26e45d48261d46dfa6102d5`:
pairs are (A=off, B=on), statistic = ratio ON/OFF − 1, `warmup_steps=20`,
bootstrap 10000 iterations, seed 20260925. Any edit invalidates every number it
produced.

## 7. Read-side tolerance already in place for killed arms

`analyze_run.py::read_jsonl` skips a torn final line and reports
`truncated_tail` / `malformed` counts (tests: `task11_evidence/tests/test_read_jsonl_tail.py`).
A SIGKILLed arm therefore still yields usable evidence.

## 8. Honest FPR gate for block 1 (replaces "zero verdicts")

The gate is: **every healthy-run verdict is explained by a named mechanism and
the FPR is quantified and low.** The reference measurement from the
pre-producer run is 1 verdict / 48 steps over 4 ranks on a ~145 ms stage,
persisted 3 windows, mechanism = within-cohort step-to-step dispersion of
±12–22 % against an observed gap of +8.8 %. Re-measure it; do not re-assert
perfection.