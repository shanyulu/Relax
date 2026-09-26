# Re-entry gate 2026-09-27 00:00-00:06 (fresh cluster session, idle 1 h)

Gate (per PR #378 acceptance protocol):
- G1 GPU/process audit: PASS — 4x RTX 4090 idle, zero GPU processes, load 7.9 (no foreign GPU work).
- G2 out-of-Ray CUDA canary (>=150 s, continuous matmul, same venv as Ray workers): PASS — survived 160.3 s (`g2_outray_canary_160s_PASS.log`).
- G3 m1 Ray-worker CUDA reproducer (30 s CUDA task, num_gpus=1, no runtime_env): FAIL x3 consecutive.
  - attempt 1: alive 13 s -> WorkerCrashedError
  - attempt 2: alive 17 s -> WorkerCrashedError
  - attempt 3: alive 17 s -> WorkerCrashedError (`m1_attempt3_alive_FAIL.log`)
- Forensics: raylet logs the kills as `Disconnecting worker, graceful=false, disconnect_type=0`
  (worker RPC dies first; raylet SIGTERM is cleanup, not the cause). No dmesg/journal OOM or NVRM
  Xid entries readable. Identical signature to the 2026-09-26 23:02 failures.

Verdict: GPU_REENTRY = FAIL. Task 11 C1/C2/C3 GPU campaign and Task 4 score reconfirmation remain
ENV_BLOCKED. Per protocol: no smoke, no campaign, no further retry loops this window.
