# Re-entry gate 2026-09-27 10:18-10:40 — GATE PASS

Environment note: overnight the container was rescheduled to a new network
identity (host IP <previous-container-private-ip> -> <current-container-private-ip>); the previous Ray cluster's
processes died with it (GCS unresponsive at the old address — connection
timeouts, all session processes gone by 10:25). A FRESH single-node Ray cluster
was started at 10:26 (session_2026-09-27_10-26-06_968071_112292, 4x GPU
detected) before the gate below.

Gate results (all on the fresh cluster unless noted):

- G1 GPU/foreign-process audit: PASS (4x RTX 4090 idle, zero GPU processes).
- G2 out-of-Ray CUDA canary, continuous matmul, same venv as workers:
  PASS, survived 160.4 s (`g2_outray_canary_160s_PASS.log`).
- G3 m1 Ray-worker CUDA reproducer (30 s CUDA task, num_gpus=1, no runtime_env):
  PASS x3 consecutive (RESULT m1-done, `M1-SURVIVED-30S` all three; on the
  degraded state yesterday the same test died at 13-17 s).
- G4 canary7 (real-actor death-site replay: captured MegatronTrainRayActor env,
  RAY_RAYLET_PID refreshed, CUDA set_device -> relax.backends.megatron import ->
  NCCL PG rank0 rendezvous): PASS — `CANARY7-SURVIVED-THEN-PG-TIMEOUT`
  (survived past the death window; the PG timeout itself is the expected
  outcome of a single-rank rendezvous) (`canary7_alive_PASS.log`,
  `g4_canary7_log.txt`).
- G5 three consecutive fresh Ray CUDA workers, 125 s each: PASS x3
  (`g5_three_workers_PASS.log`, per-worker SURVIVED-125S lines).
- G6 fresh cluster: the gate itself ran on it; node Alive, 4.0 GPU.
- G7 worker interpreter/venv fingerprint: driver and workers on
  /root/autodl-tmp/megatron-stack/venv (python 3.12.3, ray 2.58.0,
  torch 2.8.0+cu128, CUDA 12.8, driver 595.71.05, 4x RTX 4090) — identical to
  the recorded ENV_FINGERPRINT except the host IP change noted above.

Verdict: **GPU_REENTRY = PASS** at 2026-09-27 10:40 CST. The machine-level
CUDA-in-Ray fault is no longer active. Per the GPU priority rule, the window
now goes to the Task 4 final-code score reconfirmation (bounded <= 20 min,
greedy/stochastic/divergent-history only), then exclusively to the Task 11
smoke gate and C1 campaign.
