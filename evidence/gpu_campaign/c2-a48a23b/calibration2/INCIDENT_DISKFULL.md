# Disk-full incident during calibration attempt (2026-09-27 ~17:50)

Root cause: SAVE=1 Megatron checkpoints are ~7.8 GB per arm (optimizer state
included); 6 arms do not fit the 30 GB root disk. C2C2-off's job hit
ENOSPC mid-run (job.log stops at 8/48 perf steps, checkpoint truncated to
531 MB; the Ray job nonetheless exited 0 - exactly why the expected-steps
gate exists). C2C3-off's submit failed at mkdir (No space left on device).

Mitigation (before relaunch): freed 23.4 GB of pre-campaign debug
checkpoints (task11_evidence/ckpt-off{,,2,3}, 2026-09-25, not evidence),
pip caches and two idle venvs; runner now computes the checkpoint
tree-hash per arm, records it in the manifest and prunes the directory
(hash is the durable exact-equality record). C2C1-off was hashed and
pruned retroactively; its manifest carries the hash.

Archived: C2C2-off.ATTEMPT1_DISKFULL (under-stepped, INVALID),
C2C3-off.ATTEMPT1_DISKFULL (never submitted). C2C1-off remains VALID
(48/48 updates, native series, checkpoint hash recorded).
reused-ID note
- ATTEMPT2: relaunch hit 'submission ID already exists' (Ray IDs immutable after the disk-full C2C2 job); empty dir archived as C2C2-off.ATTEMPT2_EMPTYID; runner now takes --job-tag for unique namespaces.
- ATTEMPT3: crashed pre-manifest (empty mkdir only; UnboundLocalError from a mis-ordered patch line, fixed); the empty dir held no data and was removed
