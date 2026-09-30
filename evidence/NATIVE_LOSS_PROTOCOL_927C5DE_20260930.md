# Task 11 native loss/gradient supplement — 927c5de

Status: supplemental protocol. It does not replace the frozen `SAVE=1` parameter campaign or satisfy C1. It tests the loss/gradient bands that were omitted from the parameter campaign before its first ON arm.

## Fixed design

- Product `927c5de2f5a8f307cad0c87f2c7eb2b78262334d`; clean checkout only.
- Reuse the committed DP4 recipe, dataset, model snapshot and environment fingerprint in `evidence/gpu_campaign/task11_3090/ENV_FINGERPRINT.json`; the lock binds their SHA-256 values and the exact runner, extractor and protocol files. It also pins the live model/config tree, Python environment, Megatron/Bridge sources and allowlisted host launch environment.
- 4× RTX 3090, TP1/DP4, Qwen3-0.6B, global batch 32, 48 optimizer steps, seed 1234, `SAVE=0`. For every arm, the recipe's resolved NUL-delimited argv is archived and checked for the locked seed and absence of `--save`/`--save-interval`. The recipe may create the configured empty `SAVE_DIR`; only the actual `sft/<arm>` checkpoint path is forbidden.
- The runner holds Relax's shared GPU submission lock across the whole campaign. Its launcher child reuses that already-held lock; a read-only Ray/GPU preflight is required before the first arm and resources are rechecked between arms.
- Calibration order: `L-C1-off`, `L-C2-off`, `L-C3-off`, `L-C4-off`. Measurement order: `L-M1-off`, `L-M1-on`, `L-M2-on`, `L-M2-off`.
- Calibration results use the maximum absolute stepwise difference across the six pairwise contrasts of the four OFF arms, separately for loss and grad norm. Each frozen band is twice that maximum. These contrasts share arms and steps; they are not independent samples or a confidence interval.
- For each measurement pair, require 48 contiguous finite loss and grad values, matching step IDs, token-volume series, LR series and update counts. PASS means only that both series lie within the frozen OFF/OFF envelope. It does not establish unchanged accuracy, sample identity/order, bit determinism, checkpoint equivalence or overall C2 acceptance.

## Stop and verdict rules

Every arm must complete successfully, preserve its raw log and manifest, match locked code/data/environment provenance, and return the GPUs to the preflight baseline. Missing or invalid data is `INCOMPLETE`/`INVALID`; an out-of-band valid pair is `NOT_PASS`. No retries, added arms, post-hoc tolerance changes, or result-dependent stopping. On any failed arm, stop before the next arm, preserve the attempt and reconcile only that campaign's owned Ray job.

Calibration lock and tools are committed before OFF work. The OFF-only calibration result is committed before the measurement lock. That lock pins the calibration file SHA and commit; it is committed before the first ON arm. Final comparison is run only after all four locked measurement arms finish.
