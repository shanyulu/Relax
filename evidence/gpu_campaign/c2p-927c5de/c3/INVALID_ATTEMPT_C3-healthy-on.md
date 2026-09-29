{
  "arm": "C3-healthy-on",
  "attempt": 1,
  "date": "2026-09-29",
  "incident": [
    "The runner's artifact gate checked straggler_verdicts.jsonl directly under <arm>/straggler/, but the runtime nests all artifacts under run_<id>/ inside the output directory.",
    "The Ray job itself SUCCEEDED and produced the complete artifact tree (verdicts, envelopes, runtime_status, collector_status, tensorboard); only the runner's path check was wrong, so valid=False and the runner stopped before the slow arm."
  ],
  "outcome": "INVALID \u2014 retained; the stage re-runs under the fixed runner and a v2 lock.",
  "retained_run_dir": "run_0c000000",
  "root_cause_fix": "c3_campaign_927c5de._straggler_artifacts now locates files recursively and additionally counts collector_status files.",
  "schema": "C3_927C5DE_INVALID_ATTEMPT/v1"
}
