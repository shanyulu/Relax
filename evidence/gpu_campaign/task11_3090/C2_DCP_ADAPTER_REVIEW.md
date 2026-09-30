# C2 DCP adapter review — 2026-09-30

Scope: `927c5de` parameter-equivalence campaign on the single-node 4×RTX 3090
machine. This is a local engineering review of the evidence adapter, not a
maintainer approval of PR #378 or permission to load third-party checkpoints.

## Gate decision

**PASS for campaign-owned checkpoints only.** The CLI now requires a frozen
lock and the exact arm directory. Before deserializing DCP bytes it checks the
arm identity, checkpoint/output containment, absence of symlinks, successful
48-step manifest, retained checkpoint, and driver/worker provenance. The
underlying PyTorch converter still uses `weights_only=False`; arbitrary or
downloaded checkpoints remain outside this approval.

## Real-fixture checks

The retained probe DCP is 7.774 GiB under
`/root/autodl-tmp/c2p927c5de/probe/checkpoints/sft/probe-layout-927c5de/iter_0000003`.
Two independent conversions of that same source, same PyTorch build and
Megatron environment produced identical values:

| Artifact                 | SHA-256                                                            |
| ------------------------ | ------------------------------------------------------------------ |
| Source DCP tree          | `3938c9341248484db0612fac9e901c00d39bfac0b25e959a20d82acea9a6c9c2` |
| Raw PyTorch conversion   | `501ed92fae36d1455bb922b152adb72ac3bbc01b473ae812c58c964bdbeab4fb` |
| Sanitized tensor mapping | `7d7ace9c9a2222b29e19ca8657182fa5d3d5865bd2ea164b78aa760ab437b451` |

Both runs yielded 182 tensor leaves. The 48 dropped leaves have the same
canonical key/type digest (`3e99c761a404e62555670c6ec48c7a5475a20585355311aa0442e394341cfd20`):
configuration, scheduler/optimizer scalar metadata and one `argparse.Namespace`,
not tensor parameters. The sanitized mapping reloaded with
`weights_only=True`. Scalar training series are checked separately; this
adapter's equivalence claim is deliberately tensor-only.

The second conversion used ~15.6 GiB of temporary disk and was removed after
hash comparison; the original probe and its first conversion remain retained.
Focused C2 tests: **37 passed**, including old-fail/new-pass nested DCP layout,
locked-arm provenance and symlink rejection. The historical all-files
pre-commit run still fails on unrelated, already-tracked raw evidence formatting;
changed-file hooks pass. No hook was skipped for this change.

## Remaining limits

- The CLI validates the source before decoding, but it is not a sandbox against
  an adversary with write access to a campaign arm during conversion. Run only
  after the owned Ray job is terminal and keep the node exclusive.
- The 400 GiB data volume had ~354 GiB free before the temporary recheck,
  exceeding the predeclared 320 GiB start gate for eight retained arms.
- The eight-arm output is estimated at ~258 GiB. Its raw checkpoint trees
  cannot be committed under the repository's 500 KB large-file hook; retain
  them on the data volume with a hash ledger until a compliant artifact channel
  is agreed. Do not call hash-only evidence independently replayable.
