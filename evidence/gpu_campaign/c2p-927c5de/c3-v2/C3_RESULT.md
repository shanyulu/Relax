# C3 result — build `927c5de` (frozen protocol, observed evidence only)

Status: **platform evidence complete; acceptance pending the maintainer's
realtime-cadence decision.** Both arms ran once under the committed v2 lock
(`c3-v2/C3_LOCK.json`); every claim below is stage-level (JSONL) or
rollout-level (TensorBoard) — per-event latency remains UNMEASURED by
construction (protocol section 1).

## Arms

| Arm             | Job                           | Provenance                           | Artifacts                                                                                           |
| --------------- | ----------------------------- | ------------------------------------ | --------------------------------------------------------------------------------------------------- |
| `C3-healthy-on` | SUCCEEDED, resources returned | driver/worker source hashes verified | full straggler tree under `run_0c000000/` + TensorBoard events                                      |
| `C3-slow-on`    | SUCCEEDED, resources returned | driver/worker source hashes verified | same + spinner (GPU 3, 30 ms duty / 10 ms idle) started at RUNNING, killed by PID at terminal state |

The first healthy attempt hit a runner artifact-path bug (files nest under
`run_<id>/`) and is archived INVALID with full data
(`../c3/INVALID_ATTEMPT_C3-healthy-on.md`).

## Stage-level localization (JSONL, classifier: `c3_analyze_927c5de.py`)

- **Healthy baseline: 0 false positives.** 37 verdicts, all `uncertain`
  (below-floor deviations), 0 `straggler`, 0 `recovered`.
- **Slow arm: the injection target rank 3 was detected 4 times** across
  three stages — `backward-compute` w11 (dev 0.550), `all-grads-sync` w11
  (dev 6.869, `host_only_stall`), `forward-compute` w12 (dev 0.157),
  `forward-backward` w12 (dev 0.515, `host_only_stall`) — all with
  consecutive_windows = 3. 141 `uncertain`, 1 `recovered`.
- **3 non-target alarms, classified `false_positive` by the frozen
  alert-window proxy**: rank 1 `backward-compute` w14 (dev 0.154), rank 2
  `all-grads-sync` w14 (dev 1.029), rank 2 `forward-compute` w15 (dev 0.163).
  The analyzer compares these windows with target *alert* windows 11/12;
  the competing GPU process was still active at the terminal state. An alert
  window is not a complete record of the injected rank's stall intervals,
  so the proxy label does not establish the non-target alarms' cause.

## Rollout-level platform confirmation (TensorBoard record)

`perf/straggler/confirmed_straggler_rank` = **3, 3, 2, 2** (steps 16, 22, 35,
41\) with `confirmed_straggler_deviation` = 6.869, 0.515, 1.029, 0.163 — the
injected rank surfaces as the confirmed alert for the rollouts covering the
stall windows, alongside the run's `rollout_id`, `optimizer_step` and
`step_ordinal` summaries (all 48 steps). This is rollout-level corroboration
of the stage-level rank-3 detections, not a per-event join. The series
contrast with `worst_rank` (1, 1, 3, 1, 2, 2, 0, 0 — mixed uncertain) shows
the confirmed-alert metrics doing exactly what `293390e` designed: uncertain
deviations no longer mask confirmed alerts. `judged_fraction` = 1.0 for all
48 steps; `workload_incomparable_windows` grows 0 → 33 over the run (the
contended rank completes fewer samples — the honest comparability signal).

## Tail window

The slow arm's job log retains the final collector report and the clean
process-close record ("Ray shutdown successfully"); the retained collector
status files sit alongside the JSONL. No latency is derived from any of
these.

## Verdict

- Localization: **the injected target rank was convicted with stage-level
  evidence and confirmed at platform rollout cadence.**
- False-positive accounting: healthy arm 0/37; slow arm 3 non-target alarms
  (all classified false positives under the preregistered rule).
- Latency: **UNMEASURED** (no per-event identity exists in this build).
- "Realtime": rollout-cadence export observed working; the acceptance call
  is the maintainer's (Decision A, RFC #357).

The two arms, including compressed verdict/envelope JSONL and collector status,
TensorBoard events, manifests and public job logs, are archived under
`c3-v2/arms/`. The job logs replace RFC1918 addresses only; their original and
public SHA-256 values are both recorded. See `C3_PUBLIC_RECOMPUTE.md` for the
commands that reproduce the stage and platform results from these files.
