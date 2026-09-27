# C3 external-harness design (preregistered) — build `a48a23b`

Status: **pre-registered before any C3 measurement exists.**

## 1. Capability audit (fact, 2026-09-27)

The frozen envelope/verdict schema does NOT carry
`interval_end_ts / collector_ingest_ts / verdict_created_ts /
report_enqueue_ts / platform_write_ts`. Therefore:

- C3 latency is NOT measurable from existing product timestamps; it will not
  be "estimated" from logs after the fact.
- No product change is made for C3 in this phase (adding timestamps would be
  a measurement-correctness unfreeze: new PRODUCT_SHA, affected C1/C2
  reruns). Measurement is done by an **external, non-invasive harness**.

## 2. Harness (committed code, zero training-path footprint)

External observer process that:

1. Watches the ON-arm `RELAX_STRAGGLER_OUTPUT_DIR` (filesystem events) and
   records, with its own monotonic clock: envelope-file append times (proxy
   for persist), verdict-file append times (verdict visible), and the
   training log's `perf/straggler/*` merge lines (platform write visible in
   the existing perf write path).
2. Independently tails the training log to timestamp window/step markers —
   giving interval-end (training-side) anchors without touching the training
   process.
3. Writes a JSONL of (event, harness_monotonic_ts) — the harness's own
   overhead is measured (empty-dir control run) and subtracted ONLY as a
   declared constant recorded in the run manifest, never fitted post hoc.

Training thread guarantees (unchanged product): 0 HTTP, 0 socket wait, 0
blocking queue, 0 new collective on the training path — the harness is a
separate process and cannot add any.

## 3. Required C3 evidence set (all under one CAMPAIGN_LOCK)

| Evidence | Definition | Rule |
| --- | --- | --- |
| E2E latency | interval-end (log anchor) → verdict file append → perf-write line, per window | report p50/p95/p99/max; NO queueing subtraction; a "30 ms" style figure only after subtracting declared harness overhead is forbidden — report raw and overhead-adjusted side by side |
| Real localized verdict | a real run with a genuinely slowed rank (single-rank delay injection via the recipe's existing delay knob, OFF-arm-verified benign) produces a `straggler` verdict naming that rank | verdict must cite comparable-class evidence |
| Tail window | a verdict whose window closes at end-of-run | must be flushed (explicit final flush) — the silent-tail case below covers the alternative |
| Silent tail | windows with no subsequent envelope before process exit | harness records whether the final flush emitted them; the current implementation's limitation is REPORTED, not hidden |
| Platform record | the `perf/straggler/*` counters land in the existing perf write (rollout cadence) | persisted-record evidence: the written line, timestamped |

## 4. Verdict rule

C3 PASS requires: the E2E latency distribution (raw), the real-verdict case,
the tail-window case, an honest silent-tail accounting, and the platform
record — all under the locked build, PLUS the mentor's Decision A (whether
~5 s-window diagnosis + rollout-cadence export satisfies "实时上报"). Without
Decision A, C3 is at best "evidence complete, criterion reading pending".
