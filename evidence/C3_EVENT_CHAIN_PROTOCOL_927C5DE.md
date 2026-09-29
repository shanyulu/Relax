# C3 localization and platform-summary protocol — build `927c5de` (preregistered)

Status: **pre-registered before any `927c5de` C3 data exists.** Follow-up to
`REVIEW_CORRECTIONS_20260927.md` items 1, 3 and 4: at `a48a23b` the C3
latency was UNMEASURED (log-to-file-growth intervals with no event
association), the localization was 5×rank3 + 1×rank2 (the rank-2 alarm on a
non-injected rank was uncharacterized), the tail window was UNVERIFIED, and
the platform attribution of confirmed alerts had not been regressed on a
fixed public build. Product chain `a48a23b` → … → `927c5de` adds
`confirmed_straggler_deviation/rank` (`293390e`), quiet summary reads
(`4654e5a`) and state-lock isolation (`f120aa8`).

Execution deferred until GPU access; frozen before first data.

## 1. What this protocol can establish

This build has two distinct outputs, not an event-correlated telemetry chain:

- The collector's run-scoped JSONL retains stage-level detector verdicts. A
  verdict carries `cohort`, `name`, `rank`, `window_index`, and `kind`, but no
  `run_id` or unique verdict ID. Different stages can therefore share the
  same rank, window, and kind. These fields are used to localize detections;
  they are **not** an immutable event key.
- TensorBoard receives rollout-level scalar summaries, including
  `confirmed_straggler_rank` and `confirmed_straggler_deviation`. The reporter
  drains a set of verdicts and selects one confirmed alert; the scalar does
  not retain stage, window index, or a verdict ID. It confirms that an alert
  was surfaced for a rollout, not that it represents one particular JSONL
  line.

Consequently, C3 makes no per-event join and reports no observer-to-verdict,
verdict-to-file, or verdict-to-platform latency. Those quantities remain
**UNMEASURED** on `927c5de`. A future event-latency claim requires a stable
event ID propagated through the collector and platform path, plus a separately
validated clock model; neither is introduced or implied by this protocol.

## 2. Tail window

Shutdown must invoke the explicit collector flush. Preserve the pre-flush and
post-flush collector status, the raw JSONL files, and the process-close record.
For an open final window that meets the detector's normal eligibility rules,
the resulting verdict must be present in JSONL; if it does not meet those
rules, retain the detector status that explains the absence. In both cases,
zero additional verdicts may appear after close. The last verdict's kind alone
proves nothing (the withdrawn `a48a23b` inference) and must not be cited.

## 3. Non-target-rank alarms (preregistered classification)

- Healthy arm (no injection): a straggler verdict on ANY rank is a false
  positive; count and report.
- Slow arm (injection on rank 3): a non-target alarm (e.g. rank 2) is
  classified **explained secondary effect** iff its slow windows temporally
  overlap the injected rank's stall windows AND its workload stayed
  comparable; otherwise **false positive**. Both classes are reported; the
  classification rule is fixed here, before data.

## 4. Rollout-level platform confirmation

Verify on `927c5de` that
`perf/straggler/confirmed_straggler_deviation` and
`perf/straggler/confirmed_straggler_rank` appear in the TensorBoard event
files for the slow arm, alongside the run's `rollout_id`, `optimizer_step`,
and `step_ordinal` summaries. The expected confirmed rank is 3 for the
injected arm; record the scalar deviation exactly as emitted. JSONL must
independently show the stage-level rank-3 detections used for localization.

This is a rollout-level corroboration, not a JSONL-to-TensorBoard row join:
do not claim equality by window, stage, timestamp, or latency. Local unit
tests do not substitute for this real-path check (REVIEW_CORRECTIONS item 1).
Whether the observed rollout cadence meets the Task 11 interpretation of
"real-time reporting" remains a maintainer decision; before that decision,
the result is reported as **platform evidence complete, acceptance pending**.

## 5. Arms and order

Healthy baseline arm first (false-positive check), then the real-slowdown arm
(competing CUDA process on the target GPU, started only after the job reaches
RUNNING, killed by PID at terminal state — the `a48a23b` method, unchanged).
Fixed N, one-shot per arm.
