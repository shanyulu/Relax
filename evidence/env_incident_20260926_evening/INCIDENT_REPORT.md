# Task 11 / Task 4 — Shared-Machine Environment Incident, 2026-09-26 evening

**Producing investigator:** acceptance-closeout agent (Task 4 + Task 11).
**Status at writing:** machine-level fault CONFIRMED and isolated to a minimal
reproducer; not fixable from inside the container (shared 8-GPU host; driver /
host intervention out of jurisdiction). All raw logs referenced below are in
this directory.

## 1. Executive summary

Since ~15:05 on 2026-09-26, **any Ray worker process that initializes a CUDA
context is killed within 5–17 seconds** (silent SIGKILL-class death: no Python
traceback, no caught signal, no stderr, no core, plasma EOF → raylet SIGTERM of
the pgid afterwards). Identical CUDA code **outside** Ray workers runs
indefinitely on the same machine, same venv, same GPUs. No-Ray-worker processes
are unaffected regardless of name, RSS (tested at 21 GB), TMS preload, listening
ports, or duration (tested at 20 min).

This blocks, on this machine and until the fault clears:

- Task 11: OFF/ON smokes, the C1 AB/BA campaign, C2 paired runs and overlap
  traces, C3 live-vehicle measurement (all need CUDA inside Ray actor/worker
  processes).
- Task 4: the final-code score-consistency reconfirmation (SGLang engines are
  CUDA inside Ray Serve replicas). The pinned seed-contract evidence at
  `945741e` is unaffected.

## 2. Timeline (all times local)

| Time | Event |
| --- | --- |
| ≤ 15:10 | Last healthy GPU-in-Ray runs on this machine: `abba-cac4cb6-run4` S1-off/S1-on, 48 training steps each (Task 11); Task 4 B1 GPU attempts also healthy before this. |
| ~15:05 | Onset of the fault: Task 4 B1 r2–r4 CUDA contexts die 30–90 s after creation (recorded then as "GPU subsystem degradation"); Task 11 arms `abba-final`, `abba-final2`, `abba-clean` all INVALID-no-training-steps. |
| 17:11–17:52 | Prior agent restarted Ray (initially with the wrong interpreter); fresh cluster with the training-venv interpreter shows the same worker deaths. |
| 17:49 | Simple CUDA probe (matmul loop, 150 s) **survives** — outside Ray. |
| 18:00–19:30 | Three real diagnostic arms reproduce the failure deterministically: rank-0 `MegatronTrainRayActor` dies 7–26 s into `.init`, last stack frame in the `TCPStore` constructor (`relax/distributed/ray/train_actor.py:70 → dist.init_process_group → TCPStore`). Ranks 1–3 die during import (Ray exit-instruction `SystemExit: 1` from `ray._raylet.raise_sys_exit_with_custom_error_message` — an effect, not a cause). |
| 19:56–20:06 | Canary 1 (fake process title `ray::MegatronTrainRayActor.init` + listening port + plain Python): survives 600 s. |
| 20:09–20:29 | Canary 2 (title + port + TMS preload): survives. Canary 3 (title + port + TMS + **21 GB touched RSS**): survives the full 1200 s. |
| 20:35–21:20 | Ray-in-worker probes. Discovery: probes replaying a captured actor environment died because the captured `RAY_RAYLET_PID` pointed at the dead raylet of a previous cluster (Ray workers check raylet liveness and exit instantly). **All probe deaths in this window with that env are test artifacts, not the fault.** Minimal single-variable proof: stale pid 2/2 die, current pid 2/2 pass. |
| 21:34–21:38 | canary4c: FULL captured actor env (pid fixed) + megatron import + PG + GPU slot + `TCPStore` master wait (gloo) — **survives 240 s**. Env and imports exonerated. |
| 21:40–21:47 | canary7/c8 matrix (see §3): CUDA context is the sole discriminator. |
| 21:49–21:53 | Killing 165 leaked torch-inductor compile workers (fd-holders of `/dev/nvidia*`, see §4) does NOT heal the fault (canary7 retest dies). |
| 21:57–22:09 | k1–k6 (per-GPU) and m1 (no runtime_env): every CUDA-in-Ray-worker variant dies on all four GPUs. |

## 3. Minimal reproducer and the elimination matrix

Reproducer (verbatim, died at ~17 s):

```python
import ray, time
ray.init(address="auto", ignore_reinit_error=True)

@ray.remote
def plain_cuda_actor():
    import torch
    torch.cuda.set_device(0)
    x = torch.zeros(8, device="cuda")
    for i in range(30):
        time.sleep(1)
    return "ok"

print(ray.get(plain_cuda_actor.options(num_cpus=1, num_gpus=1, max_retries=0).remote(), timeout=90))
# -> ray.exceptions.WorkerCrashedError every run
```

Same code as a plain process (no Ray): healthy. Matrix (Ray worker column =
job submitted via `ray job submit` on the training-venv cluster):

| # | Context | CUDA ctx | Backend | TMS preload | runtime_env | Outcome |
| --- | --- | --- | --- | --- | --- | --- |
| canary4c | Ray actor | no | gloo | yes | full captured env | **survive** 240 s |
| c8b | Ray actor | no | nccl | yes | full captured env | **survive** (PG timeout as designed) |
| canary5 | Ray task | no | – | no | none (sys.path inject) | **survive** |
| c8a | Ray actor | yes | gloo | yes | full captured env | **die** ~12 s (last frame: TCPStore ctor) |
| canary7 | Ray actor | yes | nccl | yes | full captured env | **die** |
| c8c | Ray actor | yes | nccl | no | full minus TMS | **die** |
| canary9 | Ray actor | yes | nccl | yes | + COMPILE_THREADS=1 | **die** |
| k1 | Ray actor | yes | – | yes | full env | **die** ~6 s (plain thread + sleep!) |
| k2 | Ray actor | yes | – | yes | full env | **die** ~15 s (no thread at all) |
| k3 | Ray actor | yes (set_device only) | – | yes | full env | **die** ~15 s |
| k4/k5/k6 | Ray actor | yes (device 1/2/3) | – | yes | full env | **die** (all four GPUs) |
| m1 | Ray task | yes | – | no | **none** | **die** ~17 s |
| canary3 | plain process | no | – | yes | – | survive 1200 s, 21 GB RSS, victim title+port |
| nccl_repro | plain processes ×4 | yes | nccl | yes | – | survive (full allreduce) |
| gpu_probe | plain process | yes | – | no | – | survive 150 s |

Conclusion: the fault is exactly "Ray worker + CUDA context". Independent of
backend, TMS, threads, allocations, megatron, env vars, runtime_env, GPU index,
cluster instance, and worker port range (two clusters, 7000–8000 and
20001–29999, both affected).

## 4. Secondary findings (recorded, not root cause)

1. **165 leaked torch-inductor compile workers** held `/dev/nvidia*` fds
   (children of Serve replicas / actor workers orphaned by SIGKILL-style
   terminations since 15:12). Killed (all provably in this task's process
   tree); fd holders dropped 170 → 5. Did NOT heal the fault — the leak is a
   symptom of every death, not the cause.
2. **`RAY_RAYLET_PID` replay hazard**: replaying a captured worker environment
   after a cluster restart makes workers exit instantly (Ray liveness check).
   Any future env-replay probing must refresh that variable. This produced a
   series of false positives during this investigation (documented so it is
   never repeated).
3. Serve deployments outlive SIGKILLed drivers and keep compile pools alive;
   `ray-job.sh`'s startup cleanup handles this between submissions, but ad-hoc
   kills leak them.

## 5. What was NOT the cause (each with direct evidence)

Host memory OOM (cgroup `oom_kill=0`, 15 GB/515 GB used) · container cgroup
limits · process/thread/pid limits (unlimited/5664 used/8.2 M max) · jemalloc
preload (workers have `LD_PRELOAD` unset) · port collisions (two disjoint
worker-port ranges) · interpreter mixups (workers verified on the training
venv) · working-dir import issues (provenance gates passed) · the product code
(it is frozen at `cac4cb6` and passed 48-step arms on this same machine at
13:58–15:10).

## 6. Jurisdiction and disposition

The host is a shared 8-GPU machine (container maps physical GPUs 3,4,6,7).
Driver-level or host-level remediation (GPU reset, driver restart) would affect
other tenants and is explicitly out of scope for this container. `dmesg` is not
readable here, so the kernel-side kill record cannot be inspected.

Disposition: GPU-dependent acceptance work is **ENV_BLOCKED** until the machine
recovers (as it did once before, between the 15:05 degradation and 17:49) or is
remediated by the platform owner. The exact re-entry test is the §3 reproducer
plus `canary7`: both must survive before any smoke/campaign/B1 attempt; do not
burn a GPU window without them passing.

## 7. Re-entry test results

- 2026-09-26 22:58 — Step 1 (out-of-Ray CUDA canary, 150 s): **PASS** (the
  out-of-Ray path remains healthy).
- 2026-09-26 23:02 — Step 2 (m1 Ray-worker CUDA reproducer): **FAIL**
  (WorkerCrashedError ~3 s after `torch.cuda.set_device`), re-confirmed twice
  (m1, m1b; artifacts `reentry_20260926_2302_m1_FAIL.log`,
  `reentry_20260926_2302_m1b_FAIL.log`).

The fault is still active. GPU acceptance work on both tasks remains
ENV_BLOCKED; per protocol, no further GPU attempts until the Step-2 reproducer
passes.

- 2026-09-27 00:00-00:06 — Re-entry gate re-run after ~1 h idle (G1 audit PASS,
  G2 out-of-Ray canary 160.3 s PASS, G3 m1 reproducer FAIL x3: alive 13/17/17 s,
  same `graceful=false, disconnect_type=0` signature, no readable OOM/Xid):
  **GPU_REENTRY = FAIL**; both GPU tracks remain ENV_BLOCKED
  (`reentry_20260927_0005/RESULT.md`).
