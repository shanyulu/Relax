# Parameter replay audit — 2026-10-01

**Verdict: `PASS` for the retained-checkpoint parameter comparison only.** This replay does not change the frozen verdict or establish overall C2 acceptance, training-loss equivalence, overlap equivalence, bitwise determinism, or complete restorable-state equivalence.

| Item | Result |
|---|---|
| Product | `927c5de2f5a8f307cad0c87f2c7eb2b78262334d` |
| Replay mode | `FULL_LINEAGE_AND_NUMERIC` |
| P-M1 | 182/182 inventory entries pass; 0 violations; 0 missing tolerances |
| P-M2 | 182/182 inventory entries pass; 0 violations; 0 missing tolerances |
| GPU/training | None; read-only CPU replay of retained artifacts |
| Existing frozen verdict | Unmodified |

The replay used the pinned parameter runner, calibration and measurement locks, inventories, and retained tensor payloads. The mapping audit records the logical-to-current path mapping and confirms full lineage and numeric validation. This verifies the archived parameter comparison against the retained source files; it does not make those large source files publicly available or independently backed up.

## Machine-verifiable outputs

- `PARAMETER_REPLAY_VERDICT.json` — SHA-256 `73848f645b8043e7b37026882c8f7527a46807440918f1532b10c20e214a0f32`; embedded self-hash `f4bca13724d684a73f38945b5678dda07517cafb9fb1ece6acb5b631b6e20122`.
- `MAPPING_AUDIT.json` — SHA-256 `c04c8a6ef4cdcc77f2a7e7e6a6729921a1a3b91297122e30e509f82546d67bc7`; embedded self-hash `6a2827b499accd1b06cbbf926d89a0eff5415462a287045596ace9d0c54d845d`.

Both files were copied byte-for-byte from the replay outputs and their source/copy SHA-256 values matched. The detailed JSON preserves the per-entry deltas and inventory lineage. The original checkpoint and converted payloads remain local; hashes alone are not a portable evidence package.
