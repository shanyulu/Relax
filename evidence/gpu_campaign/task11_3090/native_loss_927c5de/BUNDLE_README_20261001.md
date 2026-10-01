# Native loss/grad replay bundle — 2026-10-01

This archive contains the eight-arm native loss/grad supplement (four OFF calibration and four measurement arms) and the two observer-only alert runs. It is a local evidence package; it has **not** been uploaded. It excludes model weights, checkpoints, the 258 GiB parameter payloads, and any claim of independent backup.

## Contents

- All eight raw arms: manifests, resolved argv, submit/dry-run/job logs, TensorBoard event files, and observer JSONL/status files for the two ON arms.
- Frozen protocol, calibration and measurement locks, calibration result, artifact ledger, and measurement verdict.
- The campaign extractor/runner, independent eight-arm auditor, alert replay tool, their CPU tests, and the generated audit reports/figures.
- `MANIFEST.sha256`, covering every packaged file except itself.

## Recompute

1. Extract the archive and verify the package ledger:

   ```bash
   sha256sum -c MANIFEST.sha256
   ```

2. Use a clean Relax checkout at product SHA `927c5de2f5a8f307cad0c87f2c7eb2b78262334d` and a Python environment with the dependencies used by that checkout. `--repo` must also have the campaign's referenced Git commit available. The package contains evidence tools and raw inputs, not a copy of the complete Relax repository or runtime environment.

3. Recompute the native loss/grad verdict with the packaged tool and locks:

   ```bash
   python tools/native_loss_gate_audit_927c5de.py \
     --repo /path/to/clean/relax-checkout \
     --raw-root raw \
     --calibration-lock locks/calibration_lock.json \
     --calibration-result locks/calibration_result.json \
     --measurement-lock locks/measurement_lock.json \
     --frozen-verdict locks/measurement_verdict.json \
     --worker-source-root-map '<exact worker_source_roots value from a manifest>=/path/to/clean/relax-checkout/relax' \
     --out /tmp/task11-native-loss-audit.md
   ```

   The mapping is exact: its left side must equal the worker source root recorded in the manifests; its right side must point to the `relax/` directory in the clean product checkout. The auditor recomputes the locked fingerprint there and rejects a mismatch. It changes neither manifests nor locks. Expected status: `PASS_WITHIN_OFF_OFF_ENVELOPE`. Keep the report outside `raw`.

4. Replay the observer-only runs against the pinned detector:

   ```bash
   python tools/replay_native_loss_alerts_20261001.py \
     --product-root /path/to/clean/relax-checkout \
     --measurement-root raw/measurement
   ```

   The saved verdict payloads must match; five offline tail candidates remain distinct from saved runtime verdicts. This replay reads files and prints JSON; it does not modify the archive.

The archive can be replayed without the original Ray working-directory cache by mapping that recorded source path to the clean product checkout. This does not reproduce the training runtime or provide independent storage. Raw evidence remains local until an immutable public location is authorized, uploaded, downloaded again, and independently replayed. A same-disk archive is not an independent backup.
