# D1/D2 correctness gate — closed at `a48a23b` (2026-09-27)

Two detector state-machine holes were reported as the blocking correctness gate
before any final GPU acceptance. Both are closed by `a962fc2` ("separate onset
and recovery") on top of `e961661`, with old-fail/new-pass evidence generated
2026-09-27 and recorded here verbatim.

## D1 — below-floor must not co-emit UNCERTAIN and RECOVERED

Semantics (per review): below-floor means *insufficient evidence to convict*,
never *positive evidence of recovery*. An active, still-slow rank below the
absolute floor must HOLD the alert, not recover it.

- Counterexample pinned by `tests/utils/straggler/test_straggler_recovery_evidence.py::test_below_floor_slow_window_holds_alert_without_recovery`:
  rank 3 alerts at 200 ms vs 100 ms peers; next window 2 ms vs 1 ms (still 2x
  slow, but below floor). Asserted: only `UNCERTAIN/below_absolute_floor` is
  emitted, `recoveries_reported == 0`, `recovery_evidence_withheld == 1`, the
  active flag remains, and a subsequent genuinely-flat window (all 1.0) is what
  produces `RECOVERED`.
- Code: `relax/utils/straggler/detector.py` — `recovered = comparable_evidence
  and not slow`; a slow-but-below-floor window takes the `elif slow and
  below_floor` branch (UNCERTAIN) and can never reach the recovery branch.

## D2 — pre-onset streak must not cross an unusable window

Semantics: PRE-ACTIVE streak counts only *adjacent usable* windows
(`previous_window == window.index - 1`); an unusable window resets the onset
streak. ACTIVE alerts, in contrast, HOLD across unusable windows (recovery
requires positive comparable evidence).

- Counterexample pinned by
  `test_onset_requires_adjacent_usable_windows` (5 gap variants:
  incomparable workload / effective class / small cohort / missing rank /
  entirely unobserved window): persist_windows=2, "slow → unusable → slow"
  must NOT alert in the third window; the alert lands only on the next
  *adjacent* slow window with `consecutive_windows == 2`.
- Companion: `test_active_alert_survives_gap_without_duplicate_onset`
  (persist 1/2/3): an ACTIVE alert survives a gap without re-announcing.

## Old-fail / new-pass record

Old build `e961661` (parent of `a962fc2`), test file taken from `a48a23b`,
CI-shaped environment (`-p ci_block_megatron`):

```
FAILED test_straggler_recovery_evidence.py::test_below_floor_slow_window_holds_alert_without_recovery
FAILED test_straggler_recovery_evidence.py::test_onset_requires_adjacent_usable_windows[incomparable]
FAILED test_straggler_recovery_evidence.py::test_onset_requires_adjacent_usable_windows[effective_class]
FAILED test_straggler_recovery_evidence.py::test_onset_requires_adjacent_usable_windows[small_cohort]
FAILED test_straggler_recovery_evidence.py::test_onset_requires_adjacent_usable_windows[missing_rank]
FAILED test_straggler_recovery_evidence.py::test_onset_requires_adjacent_usable_windows[empty]
6 failed in 0.16s
```

New build `a48a23b` (clean tree), same environment:

```
tests/utils/straggler/ + tests/tools/test_ray_job_preflight.py
  + tests/tools/test_task11_recipe_overrides.py
411 passed, 2 skipped in 50.65s
```

(The fix commit additionally records 416 passed with the full training stack
installed; the 411/2 figure above is the plugin-shaped, reproducible-on-CI
count. Both are cited, neither is inflated.)

## Verdict

```
D1_BELOW_FLOOR_STATE_MACHINE = CLOSED (pinned, old-fail/new-pass)
D2_PRE_ONSET_STREAK         = CLOSED (pinned, old-fail/new-pass)
PRODUCT_CORRECTNESS_GATE    = PASS at a48a23b
```

Scope note: this gate covers the two named state-machine holes and the full
straggler suite; it is not a blanket correctness proof of the profiler.
