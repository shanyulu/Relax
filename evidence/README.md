# Task 11 Straggler Profiler — Immutable Evidence

Branch: `evidence/task11-straggler` (append-only; never force-pushed).

Producing product SHA: `cac4cb6447154e6ae4f563eabab7fecf43dba790`
(product freeze; PR heads above it are test/docs-only).

Contents:
- `TASK11_FINAL_ACCEPTANCE_PROTOCOL.md` / `TASK11_C2C3_PROTOCOL.md` — preregistered
  acceptance protocols (frozen estimators, tolerances, seeds).
- `TASK11_FINAL_ACCEPTANCE_REPORT.md` — the acceptance report (20 sections +
  closeout addenda), including the environment-incident appendix.
- `TASK11_ENV_FINGERPRINT.json` — machine/stack fingerprint (re-captured at
  every campaign start per protocol).
- `gpu_campaign/` — every arm ever run, valid and invalid (never deleted):
  includes the unique valid pair `abba-cac4cb6-run4` (S1-off/S1-on),
  historical comparison arms, and the environment-failure arms.
- `env_incident_20260926_evening/` — the machine-level CUDA-in-Ray incident:
  reproducer, 13-case elimination matrix, canary artifacts, re-entry tests.
- `environment/pre_repair/` — pre-repair environment snapshot.
- `docs_staged/` — the bilingual user-guide sources as committed to the PR.
- Analysis scripts (`analyze_c1.py` frozen estimator, `analyze_run.py`,
  `audit_counters_v2.py`, `report_latency.py`) and their machine-recomputed
  outputs (counter conservation, latency percentiles).

Every acceptance number cited in RFC #357 / PR #378 is reproducible from a file
in this tree at the producing commit recorded with it.
