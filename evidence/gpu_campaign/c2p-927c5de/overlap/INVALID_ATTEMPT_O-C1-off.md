{
  "arm": "O-C1-off",
  "attempt": 1,
  "date": "2026-09-29",
  "incident": [
    "Runner invoked the recipe directly; the recipe's local.sh fallback ran because 'ray status' rejects a dashboard-form RAY_ADDRESS.",
    "local.sh full-local path executed 'pkill -9 python', killing the monitoring runner ~30s after submission (cgroup oom_kill=0; not OOM).",
    "The submit child (own session) survived and completed; the Ray job itself SUCCEEDED (48 steps, four rank traces written).",
    "The arm manifest could not be completed by the runner (no job_status/provenance/trace summary); valid stays False per protocol."
  ],
  "job": {
    "final_status": "SUCCEEDED",
    "submission_id": "codex-c2o-927c5de2-overlap-calibration-O-C1-off"
  },
  "lock": "O_CALIBRATION_LOCK.json (commit preceding the runner fix; RUNNER_SHA256 8a734c29..)",
  "outcome": "INVALID \u2014 retained, never silently replaced; the whole calibration stage re-runs under the fixed runner and a v2 lock.",
  "retained_traces": [
    {
      "bytes": 16722243,
      "path": "train_trace/train_overall_rank0_dp0_tp0_pp0.1790680935646283252.pt.trace.json.gz",
      "sha256": "2f1cb4232506e0414a7f2a739f62e76a16a2f5fe4c7c7088f2e3d0320622a78f"
    },
    {
      "bytes": 16788839,
      "path": "train_trace/train_overall_rank1_dp1_tp0_pp0.1790680935626842848.pt.trace.json.gz",
      "sha256": "12d74495e811bcf836def9bffa0900795b766f5a5f7dca7db2808796549e4fd8"
    },
    {
      "bytes": 16627113,
      "path": "train_trace/train_overall_rank2_dp2_tp0_pp0.1790680936072991586.pt.trace.json.gz",
      "sha256": "8c994de39a6fa8c859733d97095b88fc202ce42734b156c94b9a93723f71864a"
    },
    {
      "bytes": 16643650,
      "path": "train_trace/train_overall_rank3_dp3_tp0_pp0.1790680935506971811.pt.trace.json.gz",
      "sha256": "a975d937d5a7571a393de76c4bf67a90daf392998c2d47831fbe70dd8c9a04c9"
    }
  ],
  "root_cause_fix": "trace_campaign_927c5de.py now invokes scripts/entrypoint/ray-job.sh (entrypoint mode: flock + safe-submit preflight + env setup + RELAX_ENTRYPOINT_MODE export), so the recipe never reaches local.sh's destructive fallback.",
  "schema": "C2_927C5DE_OVERLAP_INVALID_ATTEMPT/v1"
}
