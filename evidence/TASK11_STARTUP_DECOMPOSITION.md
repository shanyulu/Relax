# TASK11 Start-up Cost Decomposition Plan (preregistered)

The N=1 pair shows a one-off **+15.699 s** on the ON arm's step 1 against a
steady-state of +0.192 % (~30 ms/step). A profiler whose per-interval cost is
microseconds should not cost 15.7 s to bring up. Before any optimisation is
proposed, the cost must be located. This plan is committed before the
measurement runs; the measurement script is `tools/straggler_startup_decompose.py`
in this evidence tree.

## What is measured (one GPU, out of Ray, same venv as the workers)

Bracketed phases, each timed with `time.perf_counter()`:

1. `import torch` + `torch.cuda.set_device(0)` + a small CUDA op (context
   ready; this phase is a CONTROL and is subtracted conceptually, not edited
   out).
2. `import relax.utils.straggler.*` (module import weight).
3. Config construction from `RELAX_STRAGGLER_*` env.
4. `StragglerRuntime.start()` — observer + event-pool allocation, timer shim
   construction, collector bind (rank-0 role) or sender connect.
5. First 100 timer start/stop pairs through the real shim (first-call paths,
   event-pool warm-up, first envelope build + ingest).
6. `report_once()` populated and empty.
7. `close()` (flush, status write).

Two variants: rank-local collector (no `COLLECTOR_ADDR`) and rank-0 collector
(`COLLECTOR_ADDR=127.0.0.1:<port>`), because bind and connect differ.

## Interpretation rules (fixed before the run)

- If phases 2-6 sum to < 1 s, the training-time +15.699 s is NOT the
  profiler's own bring-up; the candidate causes become (a) first-step
  interaction (memory pressure from the event pool, allocator behaviour), or
  (b) the shim's first-call path inside the real Megatron step (different from
  the harness's). The follow-up is a bracketed ON-arm log analysis
  (runtime_status.json timestamps vs. step-1 timestamps), not a blind
  optimisation.
- If one phase dominates, the optimisation phase targets that phase only.
- Any optimisation is judged by the SAME frozen estimators (short campaign +
  long-run protocol); no measurement is removed and no threshold changes.

## Output

`startup_decomposition_<timestamp>.json` on the evidence branch: phase table,
environment fingerprint, producing SHA. The measurement itself takes < 5 min on
one GPU and runs inside the Task 11 GPU window, after the smoke gate.
