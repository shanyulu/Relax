# Task 4 GenRM elastic scaling — evidence manifest

Raw evidence (full run directories including per-request load logs and the two
failed intermediate autoscaler runs) is preserved on the
[`evidence/task4-genrm`](https://github.com/shanyulu/Relax/tree/evidence/task4-genrm/demos/task4_genrm/results)
branch. This directory carries the machine-verdict summaries of the two passing
runs so the acceptance claims are verifiable without large artifacts; every
file is hash-pinned below.

## Passing runs

| Run | Code commit | Verdict | Key checks |
| --- | --- | --- | --- |
| Manual `1→2→1` under continuous scoring | [a2ca6cb](https://github.com/shanyulu/Relax/tree/a2ca6cb5b80fd20b372aa6e982805e345ce95dcd) | `E2E_PASS` (`verdicts.json`) | scale-out `CREATING→HEALTH_CHECKING→ACTIVE` in ~45 s on a probed free PG/GPU; scale-in `DRAINING→COMPLETED`; initial engine survived, removed engine was exactly the elastic one; elastic engine served 511 reqs; three-phase greedy short-generation prefixes identical; 4,163 load requests, 0 failures; Ray free GPUs `3→2→3` |
| Autoscaler full cycle `LOW→HIGH→STEADY→LOW'` | [105c69b](https://github.com/shanyulu/Relax/tree/105c69b59ae3896cfca7dd0e01bf5b606f00c0a7) | `E2E_PASS` (`verdicts.json`) | auto scale-out decided inside HIGH (~16 s after onset); auto scale-in decided t≈132.5 s / completed t≈137.5 s, both inside STEADY — after scale-out the load was diluted across two engines (avg token usage ~1.8 % < 5 % threshold), so this was a with-traffic scale-in, not an idle one; elastic engine served 516 reqs; 3,202 requests, 0 failures; final capacity == initial |

Re-render the timeline chart from the committed summaries:

```bash
python results/autoscaler_run_20260924_v3/plot_timeline.py
```

## Known limits of this evidence

- `max_new_tokens=8` in the consistency probe: short-generation **prefix**
  identity only, not full parseable judge output. Full reward-consistency
  comparison with per-engine attribution is pending (see the RFC's remaining
  acceptance items).
- One autoscaler round, run with experiment-tuned thresholds (per-service
  `throughput_variance_threshold=1.0`); frozen-threshold re-runs and an
  idle-phase round are pending.
- Verdicts assert Ray free GPUs returning to baseline; physical GPU memory
  recovery was captured in raw snapshots but not yet asserted together with
  PG `REMOVED` in the machine verdict.
- Single-Gateway adapter accounting; direct-client / cross-gateway drain is
  not claimed.

## Failed intermediate runs (evidence branch only)

| Run | Result | Lesson |
| --- | --- | --- |
| `autoscaler_run_20260924` (v1) | scale-out OK; scale-in never triggered | cooldown / condition-window tuning; per-request data on the evidence branch |
| `autoscaler_run_20260924_v2` (v2) | scale-out OK; scale-in never triggered | default `throughput_variance_threshold=0.1` never treated bursty short-request throughput as stable (measured variance 0.77 under low load); addressed with a per-service threshold of `1.0` |

## SHA256 (first 16 hex)

| File | sha256 |
| --- | --- |
| `e2e_run_20260924/verdicts.json` | `df8486c73471b038` |
| `e2e_run_20260924/events.json` | `d60f8740585b96c3` |
| `e2e_run_20260924/load_requests.json` (evidence branch only) | `bd9ac8f5e3613a53` |
| `autoscaler_run_20260924_v3/verdicts.json` | `0324b23107f99dab` |
| `autoscaler_run_20260924_v3/events.json` | `f7729320d16fde39` |
| `autoscaler_run_20260924_v3/timeline.json` | `df8a56f4a0ed712c` |
| `autoscaler_run_20260924_v3/scale_history.json` | `6a5790aaefb60787` |
| `autoscaler_run_20260924_v3/autoscaler.yaml` | `8ec6698a20f03295` |
| `autoscaler_run_20260924_v3/load_requests.json` (evidence branch only) | `00d2bc62f10cc0f9` |
