# Post-review validation — 2026-09-27

## Fixed scope

Product/recipe revision: `a48a23ba5a39b3410a19e91d5f362154d97c9977`.
Detector/runtime revision: `c732883`. Historical campaign: `e961661`;
its performance results must not be relabeled as results for this revision.

First execute three independent real-recipe smoke arms: OFF, ON, OFF,
8 SFT optimizer steps per arm, four GPUs, TP1/DP4, SAVE=0. Use the existing
Qwen3-0.6B snapshot and dataset hash
`44f9ddacd1e078d60d1a65d43dda76283b5ba68c6db7bbd54462126cd6a59428`.
ON uses window 5 s, persistence 3, warmup 2, report interval 10 s.
Do not tune these settings to create a verdict.

This is a **new post-fix smoke protocol**, not the prior performance campaign.
The former multi-minute CUDA/actor health gates are not claimed as rerun.
Admission requires a read-only check of jobs, Serve apps, placement groups,
GPU processes and a single local node. Hold the shared submission lock for the
whole smoke sequence. Submit through the repository's ray-job entrypoint in
safe mode, with an explicit owned job ID and worker proxy bypass.

Each arm has a 1,200 s job deadline and a 180 s submit deadline. On failure,
stop only the owned submission and stop the sequence; never retry until green.
No blanket process, Serve or placement-group cleanup is permitted. If resources
remain after the owned job exits, record cleanup incomplete and stop.

Smoke validity requires eight distinct native and perf steps, finite loss and
gradient norm, terminal SUCCEEDED, unchanged source hashes, and resource return.
ON additionally requires persisted envelopes. Zero verdicts is not evidence of
successful localization. OFF/ON timing is descriptive only, with no C1 verdict.
Archive every attempt, including failures, and the exact job/recipe/provenance.

## Historical C2 correction

`7a41161` froze S1/S2 OFF calibration before ON loss extraction. The six pairs
have 50/288 steps outside that band. Held-out OFF/OFF controls also exceed it
(5/48 and 6/48): the loss rule is not met, but this does not identify the observer
as the cause. Do not widen the band or claim numerical equivalence.
The original campaign used SAVE=0; no final checkpoint comparison exists.

## Remaining acceptance work

- C1: a new single-version, frozen campaign is required; the old result remains
  INCONCLUSIVE, not a final-code performance certification.
- C2: collect repeatable input/microbatch and checkpoint fingerprints before
  attributing loss differences. Freeze OFF-only calibration before new ON losses.
  At least two independent pairs and paired GPU traces remain required.
- C3: persist/write completion is not fsync durability. Report complete
  interval-to-verdict-to-export delays; do not subtract queueing and silently
  retain a 30 ms end-to-end PASS. The current event-time implementation leaves
  a silent tail pending until a later envelope or explicit final flush.
- Built-in actor PyTorch traces are available; substituting them for the earlier
  Nsight recipe must be declared in a separate trace protocol, not hidden.

## Recompute, not rerun-until-pass

For the historical C1 analyzer use `--expected-steps 48`, seed `20260926`,
10,000 pair resamples. Expected arithmetic: mean +0.4174268001623327%, interval
\[-1.294897986616048%, +2.022764799538646%\]. A new GPU run is not guaranteed to
reproduce the verdict category or to land inside that interval.
