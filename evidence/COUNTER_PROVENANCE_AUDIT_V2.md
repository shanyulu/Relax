# Counter provenance audit (v2)

- root scanned: `gpu_campaign`
- summary.json files scanned: 19
- arms with a dict `observation.collector_status`: 4
- arms skipped (non-dict/absent collector_status): 15
- conservation `judged + late + duplicate + invalid == envelopes`: 4/4 conserved, 0 violation(s)
- **all conserved: true**
- periodic last-line provenance counters (envelopes/judged/late/duplicate/invalid): 3 match, 0 mismatch, 3 periodic line(s) present of 4 arms
- periodic last-line ALL comparable counters (adds verdicts/windows_closed): 2 full match, 1 provenance-match-but-auxiliary-mismatch
- auxiliary-only mismatches: abba/S1-on

## Per-arm provenance

| arm | envelopes | judged | late | duplicate | invalid | conserved | persisted_envelope_lines | persisted_verdict_lines |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| abba/S1-on | 2112 | 1403 | 709 | 0 | 0 | true | 1403 | 253 |
| abba-cac4cb6-run4/S1-on | 2112 | 2112 | 0 | 0 | 0 | true | 2112 | 789 |
| abba-ce9b637/S1-on | 2112 | 1481 | 631 | 0 | 0 | true | 1481 | 540 |
| on-smoke-valid | 1760 | 1155 | 605 | 0 | 0 | true | 1155 | 43 |

## Conservation detail and derived relations

| arm | conservation equation | persisted_env == judged | persisted_env == envelopes-late-dup-invalid | persisted_verdict == verdicts | flushed_lines == persisted_env+verdicts |
| --- | --- | --- | --- | --- | --- |
| abba/S1-on | `1403 + 709 + 0 + 0 = 2112 vs envelopes=2112` | yes | yes | yes | yes |
| abba-cac4cb6-run4/S1-on | `2112 + 0 + 0 + 0 = 2112 vs envelopes=2112` | yes | yes | yes | yes |
| abba-ce9b637/S1-on | `1481 + 631 + 0 + 0 = 2112 vs envelopes=2112` | yes | yes | yes | yes |
| on-smoke-valid | `1155 + 605 + 0 + 0 = 1760 vs envelopes=1760` | yes | yes | yes | yes |

## Periodic straggler[...] line vs final collector_status

### abba/S1-on

- last periodic line: job.log line 3033, identity `rank0/tp0/pp0/vpp-1/cp0/ep0/dp0/chunk-1`
- raw: `[36m(MegatronTrainRayActor pid=87428)[0m 2026-09-26 00:54:08 | INFO | relax.utils.straggler.collector:297 straggler[rank0/tp0/pp0/vpp-1/cp0/ep0/dp0/chunk-1]: envelopes=2112 judged=1403 invalid=0 duplicate=0 late=709 windows=17 verdicts=224 stragglers=0 active=none`

| periodic field | line value | collector_status field | collector_status value | match |
| --- | --- | --- | --- | --- |
| envelopes | 2112 | envelopes | 2112 | yes |
| judged | 1403 | judged_packets | 1403 | yes |
| late | 709 | late_packets | 709 | yes |
| duplicate | 0 | duplicate_packets | 0 | yes |
| invalid | 0 | invalid_packets | 0 | yes |
| verdicts | 224 | verdicts | 253 | NO |
| windows | 17 | windows_closed | 19 | NO |

- **discrepancy**: verdicts=224 vs verdicts=253; windows=17 vs windows_closed=19

### abba-cac4cb6-run4/S1-on

- last periodic line: job.log line 4286, identity `rank0/tp0/pp0/vpp-1/cp0/ep0/dp0/chunk-1`
- raw: `[36m(MegatronTrainRayActor pid=536111)[0m 2026-09-26 14:48:28 | INFO | relax.utils.straggler.collector:297 straggler[rank0/tp0/pp0/vpp-1/cp0/ep0/dp0/chunk-1]: envelopes=2112 judged=2112 invalid=0 duplicate=0 late=0 windows=143 verdicts=789 stragglers=20 active=none`

| periodic field | line value | collector_status field | collector_status value | match |
| --- | --- | --- | --- | --- |
| envelopes | 2112 | envelopes | 2112 | yes |
| judged | 2112 | judged_packets | 2112 | yes |
| late | 0 | late_packets | 0 | yes |
| duplicate | 0 | duplicate_packets | 0 | yes |
| invalid | 0 | invalid_packets | 0 | yes |
| verdicts | 789 | verdicts | 789 | yes |
| windows | 143 | windows_closed | 143 | yes |

- exact match on every comparable counter in the periodic line.

### abba-ce9b637/S1-on

- last periodic line: job.log line 3995, identity `rank0/tp0/pp0/vpp-1/cp0/ep0/dp0/chunk-1`
- raw: `[36m(MegatronTrainRayActor pid=302854)[0m 2026-09-26 11:42:28 | INFO | relax.utils.straggler.collector:297 straggler[rank0/tp0/pp0/vpp-1/cp0/ep0/dp0/chunk-1]: envelopes=2112 judged=1481 invalid=0 duplicate=0 late=631 windows=150 verdicts=540 stragglers=8 active=none`

| periodic field | line value | collector_status field | collector_status value | match |
| --- | --- | --- | --- | --- |
| envelopes | 2112 | envelopes | 2112 | yes |
| judged | 1481 | judged_packets | 1481 | yes |
| late | 631 | late_packets | 631 | yes |
| duplicate | 0 | duplicate_packets | 0 | yes |
| invalid | 0 | invalid_packets | 0 | yes |
| verdicts | 540 | verdicts | 540 | yes |
| windows | 150 | windows_closed | 150 | yes |

- exact match on every comparable counter in the periodic line.

### on-smoke-valid

- no periodic `straggler[...]` line found (job.log present: false; other logs: {'job.log': False, 'submit.log': True, 'off-smoke-submit.log': False})

## Arms skipped (no dict collector_status)

- `abba/S1-off`: collector_status kind = str
- `abba/S1-on.attempt1-killed-by-operator`: collector_status kind = str
- `abba-cac4cb6/S1-off`: collector_status kind = str
- `abba-cac4cb6/S1-on`: collector_status kind = str
- `abba-cac4cb6-run2/S1-off`: collector_status kind = str
- `abba-cac4cb6-run2/S1-on`: collector_status kind = str
- `abba-cac4cb6-run3/S1-off`: collector_status kind = str
- `abba-cac4cb6-run3/S1-on`: collector_status kind = str
- `abba-cac4cb6-run4/S1-off`: collector_status kind = str
- `abba-cac4cb6-run4/S2-on`: collector_status kind = str
- `abba-ce9b637/S1-off`: collector_status kind = str
- `abba-final/S1-off`: collector_status kind = str
- `abba-final2/S1-off`: collector_status kind = str
- `off-smoke`: collector_status kind = str
- `on-smoke`: collector_status kind = str

## Verdict

Conservation holds everywhere that it is evaluable. No hand-written counters.
