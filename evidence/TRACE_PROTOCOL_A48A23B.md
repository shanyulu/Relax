# Overlap trace protocol (preregistered) — build `a48a23b`

Status: **pre-registered before any trace data exists.**

## 1. Backend declaration (fixed NOW, before any run)

Primary backend: **torch.profiler (Kineto/CUPTI)**, driven by a committed
harness with programmatic export — because Nsight Systems could not be
installed in this environment, as recorded below. This is an environment
constraint declared before any trace was taken; it is NOT a post-hoc
downgrade after unsatisfactory Nsight results (no Nsight results exist).

### Nsight availability record (2026-09-27)

- `command -v nsys` → absent on the host.
- pip package `nsight-systems` in a dedicated venv
  (`/root/autodl-tmp/tools/nsight-systems/venv-standalone`, isolated from the
  training venv): installs but ships no `nsys` CLI and no importable module —
  not usable.
- Official standalone tarball URLs under
  `developer.download.nvidia.com/nsight-systems/…` return a 381-byte XML
  error page through this host's egress policy — download blocked.
- Record: NSYS_PATH=none, NSYS_VERSION=none,
  INSTALL_METHOD=attempted (pip-standalone-venv + direct-download), blocked;
  no pollution of the training venv occurred (the venv used is disposable).
- Backend dry-run verification (2026-09-27, training venv, CPU + CUDA probe,
  no acceptance state touched): torch 2.8.0+cu128, `torch.profiler` CPU
  profile OK, CUDA/CUPTI profile OK (28 event groups on a 64×64 matmul).
  The declared primary backend is functional in this environment.
- If Nsight becomes installable later, traces may be UPGRADED to Nsight for
  qualitative cross-checking, but the quantitative verdict stays on the
  declared backend unless a new protocol is preregistered.

## 2. Trace experiment specification

| Parameter | Value |
| --- | --- |
| Build | `a48a23b` clean tree, CAMPAIGN_LOCK-referenced |
| Arms | OFF and ON, same code / recipe / dataset / step count / GPU topology (TP1/DP4, 4×RTX4090); the ONLY difference is `RELAX_STRAGGLER_ENABLE` |
| Steps traced | a fixed window: warm-up 8 steps, then trace 16 steps (committed in the run manifest; identical for OFF and ON) |
| Trace overhead | traces run in a SEPARATE pair of arms; trace-ON data is NEVER used for C1 overhead estimation |

## 3. Programmatic metrics (computed by committed script, not by eye)

For each of OFF and ON, over the traced window:

- `compute_busy` — union of kernel-execution intervals on the compute stream
- `comm_busy` — union of NCCL kernel intervals
- `overlap_duration` — measure of (compute ∩ comm)
- `overlap_ratio` — overlap_duration / min(compute_busy, comm_busy)
- `device_idle` — traced window minus (compute ∪ comm)
- `host_gap` — sum of gaps between consecutive device-side launches
- `new_global_sync` — count of NEW grid-wide synchronisation primitives
  introduced by ON vs OFF (device-wide events/barriers attributable to the
  profiler path; must be 0 by design and is asserted)

Acceptance: overlap_ratio(ON) ≥ overlap_ratio(OFF) − δ and no new global
sync, with δ frozen in the C2 protocol's tolerance table BEFORE the traces
are taken. A Chrome/Perfetto timeline screenshot is not evidence; the
exported raw events plus the script's JSON output are.

## 4. What this protocol does not claim

- No DP4-cross-rank or TP2×DP2 topology claims from a TP1/DP4 trace; if a
  second topology is traced, it is a separate declared arm pair with its own
  manifest.
- Trace quality issues (dropped events, CUPTI buffer overflow) are recorded,
  never silently retried until pretty.
