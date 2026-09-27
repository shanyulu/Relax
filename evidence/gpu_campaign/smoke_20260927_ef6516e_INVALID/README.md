# smoke_20260927_ef6516e — INVALID (contaminated working tree), forensics preserved

Verdict: **the whole smoke attempt at `ef6516e` on 2026-09-27 12:48–13:01 is
INVALID and is not reusable evidence for any version.** It is preserved here
because its failure mode is instructive and was fully root-caused.

## What happened

The smoke driver pins the product head and asserts a clean tree before each
arm. SM1-off (12:48–12:53, valid) ran on a clean `ef6516e`. During SM2-on
(12:53–12:57), the developer edited `relax/utils/straggler/detector.py` in the
worktree CONCURRENTLY with the arm's `ray job submit --working-dir` packaging:
the job therefore packaged a half-edited tree that corresponds to no commit.
SM3-off was correctly REFUSED by the clean-tree assert ("refusing to run an
arm on a dirty tree").

## Observed anomaly in SM2-on (for the record)

- exit=0, 5 training steps completed (training itself was healthy — the
  profiler is fail-open by design, which is exactly why a broken profiler
  package did not surface as a training failure);
- `INVALID-observer-silent`: the collector ingested only 2 of the ~220
  expected envelopes; rank1/rank2 observers recorded 55 intervals each and
  their senders reported `sent=55, send_errors=0, connected=True`, while
  rank0/rank3 observers recorded 0 intervals;
- the run-scoped status files were still being written 16 s before job end,
  so the counts are real observations of the contaminated code, not stale
  snapshots.

The micro-mechanism inside the half-edited detector (which path swallowed the
senders' envelopes) is not worth root-causing: the code has no commit identity.

## The controlled re-run decides

The identical smoke re-run on the COMMITTED `e961661` tree (nothing else
changed; `smoke_20260927_e961661`) produced a valid ON arm with **239
envelopes on disk / 220 ingested, judged 220/220, late=0, duplicate=0,
invalid=0, forward-backward coverage present** — the expected per-step rate.
The `ef6516e` attempt's failure is therefore attributed to the concurrent-edit
contamination, not to a product regression at any commit.

## Rule adopted (protocol §7 addition)

No code edits in any worktree while one of its arms is in flight; the
clean-tree assert is a necessary but not sufficient guard because the packaging
happens after the assert. The campaign driver keeps the assert AND the
campaign runs only against committed, pushed SHAs.
