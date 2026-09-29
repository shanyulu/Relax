# C2 parameter campaign — storage and DCP adapter escalation (927c5de)

Status: **parameter arms remain STOPPED.** The layout probe (`PROBE_LAYOUT_RECORD.json`)
settled both blockers on 2026-09-29; this document records the adapter work completed
since and the decision required to resume. No formal parameter lock exists.

## 1. Blockers (measured, not estimated)

| Blocker | Measured value | Consequence |
| --- | --- | --- |
| Checkpoint layout | Megatron DCP sharded (`__0..3_0.distcp` + `.metadata`), 9 files, 7.774 GiB | The inventory exporter correctly refuses DCP; the checklist requires a separately reviewed adapter before any formal lock |
| Storage gate | `8 × 7.774 × 1.20 = 74.63 GiB` required vs ~67 GiB free | FAILS the checklist's entry gate before payload expansion is even counted |

## 2. Adapter: implemented, tested, proven on the real fixture — PROPOSED_PENDING_REVIEW

`tools/c2_parameter_dcp_adapter_927c5de.py` converts one retained DCP iteration with
torch's own offline utility (`torch.distributed.checkpoint.format_utils.dcp_to_torch_save`),
then sanitises the result to a plain `{key: Tensor}` mapping (parameter equivalence is
defined over tensors; every dropped non-tensor leaf is recorded by key and type).
Findings baked into the tool after real-fixture failures:

- Megatron DCP byte payloads pickle-reference `megatron.core`: the adapter REQUIRES the
  training venv interpreter with the Megatron-LM source on PYTHONPATH (the checkpoint's
  own writing environment) and fails closed otherwise.
- The raw conversion carries `omegaconf`/`argparse` objects that a `weights_only` load
  must refuse; only the sanitised payload sits under the inventory root (raw conversion
  retained in a sibling directory), and the sanitised payload itself is validated with
  `weights_only=True` before anything downstream may read it.

End-to-end proof on the probe's own 7.774 GiB DCP fixture (2026-09-29):
adapter → 182 tensors (178 decoder, 1 embedding, 3 fused optimizer; 48 non-tensor leaves
recorded and dropped) → `c2_parameter_inventory_927c5de.export_inventory` → verdict-readable
(182/182, dtypes |u1 ×169, bfloat16 ×10, <f4 ×3). Sanitised payload sha256
`7d7ace9c9a2222b2…`; CPU guards: 3 passed.

Reviewer checklist (what "separately reviewed" must confirm before a formal lock may
reference this adapter): the converter choice and its `weights_only=False` byte-payload
path is acceptable for this campaign's own arm output; the sanitise-drop list contains
nothing parameter-equivalence needs; the sanitised payload's `weights_only` posture is
the same as the inventory exporter's; the conversion is deterministic for a fixed source
tree and torch build.

## 3. Storage: the real arithmetic after the end-to-end run

Per arm, transient peak ≈ DCP 7.8 + raw conversion 7.8 + sanitised 7.8 + inventory
payloads 8.9 ≈ **32.3 GiB**; stable retention (DCP tree + payloads) ≈ **16.7 GiB**.
Eight arms ≈ **134 GiB stable** plus transients — infeasible on the 67 GiB data disk.

## 4. Decision requested (any one resumes the campaign)

1. Provide ≥ ~150 GiB of durable storage for the campaign window; run the frozen
   eight-arm protocol unchanged, or
2. Review the adapter (checklist above) AND approve a retention-policy amendment
   (preregistered before any arm runs, e.g.: DCP tree retained until its sanitised
   payload and inventory are hash-verified; the raw conversion deleted after hashing —
   it is deterministically re-derivable; payloads retained through the verdict), or
3. Accept parameter equivalence as INCOMPLETE with this blocker documented.

Until one lands, the historical `a48a23b` verdict stands: INCOMPLETE — 0 metric
violations, 2 missing parameter-evidence items.
