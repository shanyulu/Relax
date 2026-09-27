# C3 event-chain protocol — build `927c5de` (preregistered)

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

## 1. Event identity (the unit of every latency claim)

Every verdict carries (run_id, rank, window index, kind). The chain for one
event is: interval completion (observer) → verdict emission (detector) →
JSONL persistence (collector) → platform visibility (tensorboard scalar).
Latency is reported **per event identity** as raw durations between adjacent
chain points. p50/p95 may be cited only over event-associated samples;
anything else is reported UNMEASURED. No subtraction of unrelated intervals.

## 2. Clock comparability (preregistered check, run once per session)

Collector and trainer may live in different processes. Before any latency is
claimed: record both processes' clocks at a common marked event (a synthetic
envelope ingested at a known trainer timestamp) and verify the mapping is
linear and stable within the session; report the measured skew. A session
without this check cannot claim latency numbers.

## 3. Tail window

Shutdown must close the last accepted window via the explicit flush; the
evidence is (a) a flush-produced verdict for the previously open window and
(b) zero verdicts after close. The last verdict's kind alone proves nothing
(the withdrawn `a48a23b` inference) and must not be cited.

## 4. Non-target-rank alarms (preregistered classification)

- Healthy arm (no injection): a straggler verdict on ANY rank is a false
  positive; count and report.
- Slow arm (injection on rank 3): a non-target alarm (e.g. rank 2) is
  classified **explained secondary effect** iff its slow windows temporally
  overlap the injected rank's stall windows AND its workload stayed
  comparable; otherwise **false positive**. Both classes are reported; the
  classification rule is fixed here, before data.

## 5. Platform attribution regression

Verify on `927c5de` that `perf/straggler/confirmed_straggler_deviation` and
`confirmed_straggler_rank` appear in the tensorboard event files and match
the JSONL verdicts of the same event identity (value and window). Local unit
tests do not substitute (REVIEW_CORRECTIONS item 1).

## 6. Arms and order

Healthy baseline arm first (false-positive check), then the real-slowdown arm
(competing CUDA process on the target GPU, started only after the job reaches
RUNNING, killed by PID at terminal state — the `a48a23b` method, unchanged).
Fixed N, one-shot per arm.
