# Straggler reporting-latency report

- root: `gpu_campaign`
- ON arms examined: 4
- default window length when not declared: 5.0 s

The chain hop names are: `interval complete -> collector ingest -> verdict creation -> persisted line`. A hop is reported as **ABSENT** when the artifacts genuinely carry no timestamp for it; the required field is named rather than replaced by a proxy.

## abba/S1-on

- envelopes: 1403 rows; verdicts: 253 rows
- envelope keys observed: barrier, cohort, device_ms, host_end, host_ms, host_start, label, log_level, measurement_kind, name, rank, reason, run_id, seq, workload, world_size
- verdict keys observed: candidate_causes, cohort, cohort_size, consecutive_windows, deviation, facts, host_only, kind, label, measurement_kind, name, rank, rank_device_ms, rank_host_ms, reason, reference_device_ms, reference_host_ms, window_index
- envelope time fields present: ['host_start', 'host_end', 'host_ms', 'device_ms']
- verdict time fields present (durations only): ['rank_host_ms', 'reference_host_ms', 'rank_device_ms', 'reference_device_ms']

### Latency chain

| hop | availability | field / required field | p50 | p95 | p99 | max |
| --- | --- | --- | --- | --- | --- | --- |
| interval complete | available | `host_end` (monotonic s) | 9035592.110753 | 9035611.892140 | 9035613.362297 | 9035613.678248 |
| collector ingest | ABSENT | needs ingest_host_s, ingest_host, collector_recv_host_s, recv_host_s, received_at | - | - | - | - |
| verdict creation | ABSENT | needs verdict_host_s, created_host_s, verdict_created_host_s, created_at, emit_host_s | - | - | - | - |
| persisted line | ABSENT | needs persist_host_s, written_host_s, flush_host_s, persisted_at | - | - | - | - |
| overall interval -> persisted | ABSENT | needs collector_recv_host_s, created_at, created_host_s, emit_host_s, flush_host_s, ingest_host, ingest_host_s, persist_host_s, persisted_at, received_at, recv_host_s, verdict_created_host_s, verdict_host_s, written_host_s | - | - | - | - |

- **collector ingest — not derivable.** no ingest timestamp is recorded on the envelope: the JSONL is written after the collector has already consumed the packet, so ingest time is not observable. Needed field(s): `ingest_host_s, ingest_host, collector_recv_host_s, recv_host_s, received_at`.
- **verdict creation — not derivable.** verdict records carry duration fields (rank_host_ms, reference_host_ms) but no creation timestamp. Needed field(s): `verdict_host_s, created_host_s, verdict_created_host_s, created_at, emit_host_s`.
- **persisted line — not derivable.** JSONL lines carry no per-line write timestamp; only whole-file mtime exists, which is not per record. Needed field(s): `persist_host_s, written_host_s, flush_host_s, persisted_at`.

### Schedule-dependent delay (derived)

- window length used: 5.0 s (source: manifest.relax_env.RELAX_STRAGGLER_WINDOW_S)
- cohort anchors (min envelope `host_start` per cohort): {'topo0:dense:0:0:-1:-1:0:0:0': 9035523.525580518}
- matched verdicts: 253/253; unique envelope matches: 34; trigger `host_ms` equals verdict `rank_host_ms`: 124
| quantity | n | min | p50 | p95 | p99 | max | mean |
| --- | --- | --- | --- | --- | --- | --- | --- |
| seconds | 253 | 0.069922 | 0.779119 | 4.571614 | 4.862531 | 4.984792 | 1.712709 |

- gaps outside `[0, window_s]`: 0; unmatched verdicts: 0

| verdict kind | n | p50 s | p95 s | max s |
| --- | --- | --- | --- | --- |
| uncertain | 253 | 0.779119 | 4.571614 | 4.984792 |

- context: measured interval `host_ms` p50 2.160806 ms, p95 141.021896 ms, p99 171.847384 ms, max 45649.629531 ms (the profiled stage durations, not latency hops)

## abba-cac4cb6-run4/S1-on

- envelopes: 2112 rows; verdicts: 789 rows
- envelope keys observed: barrier, cohort, device_ms, host_end, host_ms, host_start, label, log_level, measurement_kind, name, rank, reason, run_id, seq, workload, world_size
- verdict keys observed: candidate_causes, cohort, cohort_size, consecutive_windows, deviation, facts, host_only, kind, label, measurement_kind, name, rank, rank_device_ms, rank_host_ms, reason, reference_device_ms, reference_host_ms, window_index
- envelope time fields present: ['host_start', 'host_end', 'host_ms', 'device_ms']
- verdict time fields present (durations only): ['rank_host_ms', 'reference_host_ms', 'rank_device_ms', 'reference_device_ms']

### Latency chain

| hop | availability | field / required field | p50 | p95 | p99 | max |
| --- | --- | --- | --- | --- | --- | --- |
| interval complete | available | `host_end` (monotonic s) | 9085059.509058 | 9085612.887083 | 9085660.186960 | 9085665.526507 |
| collector ingest | ABSENT | needs ingest_host_s, ingest_host, collector_recv_host_s, recv_host_s, received_at | - | - | - | - |
| verdict creation | ABSENT | needs verdict_host_s, created_host_s, verdict_created_host_s, created_at, emit_host_s | - | - | - | - |
| persisted line | ABSENT | needs persist_host_s, written_host_s, flush_host_s, persisted_at | - | - | - | - |
| overall interval -> persisted | ABSENT | needs collector_recv_host_s, created_at, created_host_s, emit_host_s, flush_host_s, ingest_host, ingest_host_s, persist_host_s, persisted_at, received_at, recv_host_s, verdict_created_host_s, verdict_host_s, written_host_s | - | - | - | - |

- **collector ingest — not derivable.** no ingest timestamp is recorded on the envelope: the JSONL is written after the collector has already consumed the packet, so ingest time is not observable. Needed field(s): `ingest_host_s, ingest_host, collector_recv_host_s, recv_host_s, received_at`.
- **verdict creation — not derivable.** verdict records carry duration fields (rank_host_ms, reference_host_ms) but no creation timestamp. Needed field(s): `verdict_host_s, created_host_s, verdict_created_host_s, created_at, emit_host_s`.
- **persisted line — not derivable.** JSONL lines carry no per-line write timestamp; only whole-file mtime exists, which is not per record. Needed field(s): `persist_host_s, written_host_s, flush_host_s, persisted_at`.

### Schedule-dependent delay (derived)

- window length used: 5.0 s (source: manifest.relax_env.RELAX_STRAGGLER_WINDOW_S)
- cohort anchors (min envelope `host_start` per cohort): {'topo0:dense:0:0:-1:-1:0:0:0': 9084370.58479416}
- matched verdicts: 787/789; unique envelope matches: 787; trigger `host_ms` equals verdict `rank_host_ms`: 787
| quantity | n | min | p50 | p95 | p99 | max | mean |
| --- | --- | --- | --- | --- | --- | --- | --- |
| seconds | 787 | 0.004057 | 2.387790 | 4.697008 | 4.943884 | 4.963068 | 2.402021 |

- gaps outside `[0, window_s]`: 0; unmatched verdicts: 2

| verdict kind | n | p50 s | p95 s | max s |
| --- | --- | --- | --- | --- |
| recovered | 19 | 1.936545 | 4.451867 | 4.542473 |
| straggler | 20 | 1.683743 | 3.980976 | 4.405594 |
| uncertain | 748 | 2.397082 | 4.703784 | 4.963068 |

- context: measured interval `host_ms` p50 1.986880 ms, p95 229.829861 ms, p99 285.048448 ms, max 57423.677353 ms (the profiled stage durations, not latency hops)

## abba-ce9b637/S1-on

- envelopes: 1481 rows; verdicts: 540 rows
- envelope keys observed: barrier, cohort, device_ms, host_end, host_ms, host_start, label, log_level, measurement_kind, name, rank, reason, run_id, seq, workload, world_size
- verdict keys observed: candidate_causes, cohort, cohort_size, consecutive_windows, deviation, facts, host_only, kind, label, measurement_kind, name, rank, rank_device_ms, rank_host_ms, reason, reference_device_ms, reference_host_ms, window_index
- envelope time fields present: ['host_start', 'host_end', 'host_ms', 'device_ms']
- verdict time fields present (durations only): ['rank_host_ms', 'reference_host_ms', 'rank_device_ms', 'reference_device_ms']

### Latency chain

| hop | availability | field / required field | p50 | p95 | p99 | max |
| --- | --- | --- | --- | --- | --- | --- |
| interval complete | available | `host_end` (monotonic s) | 9073877.506720 | 9074447.290352 | 9074499.410679 | 9074504.710349 |
| collector ingest | ABSENT | needs ingest_host_s, ingest_host, collector_recv_host_s, recv_host_s, received_at | - | - | - | - |
| verdict creation | ABSENT | needs verdict_host_s, created_host_s, verdict_created_host_s, created_at, emit_host_s | - | - | - | - |
| persisted line | ABSENT | needs persist_host_s, written_host_s, flush_host_s, persisted_at | - | - | - | - |
| overall interval -> persisted | ABSENT | needs collector_recv_host_s, created_at, created_host_s, emit_host_s, flush_host_s, ingest_host, ingest_host_s, persist_host_s, persisted_at, received_at, recv_host_s, verdict_created_host_s, verdict_host_s, written_host_s | - | - | - | - |

- **collector ingest — not derivable.** no ingest timestamp is recorded on the envelope: the JSONL is written after the collector has already consumed the packet, so ingest time is not observable. Needed field(s): `ingest_host_s, ingest_host, collector_recv_host_s, recv_host_s, received_at`.
- **verdict creation — not derivable.** verdict records carry duration fields (rank_host_ms, reference_host_ms) but no creation timestamp. Needed field(s): `verdict_host_s, created_host_s, verdict_created_host_s, created_at, emit_host_s`.
- **persisted line — not derivable.** JSONL lines carry no per-line write timestamp; only whole-file mtime exists, which is not per record. Needed field(s): `persist_host_s, written_host_s, flush_host_s, persisted_at`.

### Schedule-dependent delay (derived)

- window length used: 5.0 s (source: manifest.relax_env.RELAX_STRAGGLER_WINDOW_S)
- cohort anchors (min envelope `host_start` per cohort): {'topo0:dense:0:0:-1:-1:0:0:0': 9073224.422683986}
- matched verdicts: 538/540; unique envelope matches: 538; trigger `host_ms` equals verdict `rank_host_ms`: 538
| quantity | n | min | p50 | p95 | p99 | max | mean |
| --- | --- | --- | --- | --- | --- | --- | --- |
| seconds | 538 | 0.012005 | 2.495346 | 4.720137 | 4.953981 | 4.996185 | 2.471253 |

- gaps outside `[0, window_s]`: 0; unmatched verdicts: 2

| verdict kind | n | p50 s | p95 s | max s |
| --- | --- | --- | --- | --- |
| recovered | 7 | 1.230545 | 4.294188 | 4.294188 |
| straggler | 8 | 1.995592 | 4.784611 | 4.784611 |
| uncertain | 523 | 2.498076 | 4.720137 | 4.996185 |

- context: measured interval `host_ms` p50 2.400795 ms, p95 226.648567 ms, p99 266.830683 ms, max 46773.848869 ms (the profiled stage durations, not latency hops)

## on-smoke-valid

- envelopes: 1155 rows; verdicts: 43 rows
- envelope keys observed: barrier, cohort, device_ms, host_end, host_ms, host_start, label, log_level, name, rank, reason, run_id, seq, workload, world_size
- verdict keys observed: candidate_causes, cohort, cohort_size, consecutive_windows, deviation, facts, host_only, kind, label, measurement_kind, name, rank, rank_device_ms, rank_host_ms, reason, reference_device_ms, reference_host_ms, window_index
- envelope time fields present: ['host_start', 'host_end', 'host_ms', 'device_ms']
- verdict time fields present (durations only): ['rank_host_ms', 'reference_host_ms', 'rank_device_ms', 'reference_device_ms']

### Latency chain

| hop | availability | field / required field | p50 | p95 | p99 | max |
| --- | --- | --- | --- | --- | --- | --- |
| interval complete | available | `host_end` (monotonic s) | 9026972.831227 | 9026989.139741 | 9026990.699333 | 9026991.005991 |
| collector ingest | ABSENT | needs ingest_host_s, ingest_host, collector_recv_host_s, recv_host_s, received_at | - | - | - | - |
| verdict creation | ABSENT | needs verdict_host_s, created_host_s, verdict_created_host_s, created_at, emit_host_s | - | - | - | - |
| persisted line | ABSENT | needs persist_host_s, written_host_s, flush_host_s, persisted_at | - | - | - | - |
| overall interval -> persisted | ABSENT | needs collector_recv_host_s, created_at, created_host_s, emit_host_s, flush_host_s, ingest_host, ingest_host_s, persist_host_s, persisted_at, received_at, recv_host_s, verdict_created_host_s, verdict_host_s, written_host_s | - | - | - | - |

- **collector ingest — not derivable.** no ingest timestamp is recorded on the envelope: the JSONL is written after the collector has already consumed the packet, so ingest time is not observable. Needed field(s): `ingest_host_s, ingest_host, collector_recv_host_s, recv_host_s, received_at`.
- **verdict creation — not derivable.** verdict records carry duration fields (rank_host_ms, reference_host_ms) but no creation timestamp. Needed field(s): `verdict_host_s, created_host_s, verdict_created_host_s, created_at, emit_host_s`.
- **persisted line — not derivable.** JSONL lines carry no per-line write timestamp; only whole-file mtime exists, which is not per record. Needed field(s): `persist_host_s, written_host_s, flush_host_s, persisted_at`.

### Schedule-dependent delay (derived)

- window length used: 5.0 s (source: not recorded in arm manifest)
- **assumption-dependent**: the window length is not recorded in this arm's manifest; the value above is the CLI default.
- cohort anchors (min envelope `host_start` per cohort): {'topo0:dense:0:0:-1:-1:0:0:0': 9026908.137069909}
- matched verdicts: 43/43; unique envelope matches: 6; trigger `host_ms` equals verdict `rank_host_ms`: 23
| quantity | n | min | p50 | p95 | p99 | max | mean |
| --- | --- | --- | --- | --- | --- | --- | --- |
| seconds | 43 | 0.094053 | 0.422531 | 4.396113 | 4.880301 | 4.880301 | 1.555275 |

- gaps outside `[0, window_s]`: 0; unmatched verdicts: 0

| verdict kind | n | p50 s | p95 s | max s |
| --- | --- | --- | --- | --- |
| recovered | 14 | 0.800351 | 4.362175 | 4.557336 |
| straggler | 29 | 0.389180 | 4.396113 | 4.880301 |

- context: measured interval `host_ms` p50 2.212258 ms, p95 146.438671 ms, p99 168.349100 ms, max 45594.270118 ms (the profiled stage durations, not latency hops)

## What could not be derived, and what is needed

- **collector ingest timestamp** — absent. The envelope JSONL is written after the collector already consumed the packet; add an `ingest_host_s` (or `collector_recv_host_s`) stamped when the receiver accepts the packet, and surface it on the envelope row.
- **verdict creation timestamp** — absent. Verdicts carry only durations (`rank_host_ms`, `reference_host_ms`). Add a `verdict_host_s`/`created_host_s` stamped when the detector emits the verdict.
- **persisted-line timestamp** — absent. Lines carry no write timestamp. Add a `persist_host_s` (or write a per-record timestamp) so the flush hop is measurable; whole-file mtime is not a per-record value.
- **overall interval -> persisted** — therefore absent; it is the sum of the absent hops.
- **schedule-dependent delay** — derivable for arms whose window length is recorded, by reconstructing the window close from the cohort anchor and `window_index` (see the definition above). For arms without a recorded window length the value is flagged assumption-dependent.
