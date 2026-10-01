# Task 11 native loss/grad gate audit — 2026-10-01

Status: **PASS_WITHIN_OFF_OFF_ENVELOPE**

The independent read-only audit parsed all four OFF calibration jobs and all four measurement jobs from retained logs. It validated lock hashes and lineage, exact arm order and pairs, per-arm manifest/log/argv hashes, 48 finite contiguous steps, source fingerprints, OFF/ON labels, and runtime observer activation. It then recalculated the OFF envelope and measurement verdict.

Product: `927c5de2f5a8f307cad0c87f2c7eb2b78262334d`  
Calibration lock self-hash: `4e081f5298c02919b27f4f1b79f034f3842909c37446a18746eb77e96eeb4e67`  
Calibration result file SHA-256: `8772372921343085097dd01e9ec2e584f5aa3ce5d68e30605892341c7bed33e4`  
Measurement lock self-hash: `7ba47ae2750da1353bda8395d78415c8a863dd1b218aef24faafba0be3fdf936`  
Frozen verdict file SHA-256: `73d8e956f5f8b2c71487efeee935623fab2d800239d80fca257d96954addc08e`  
Normalized argv SHA-256 (only per-arm `--tb-experiment-name` normalized): `d598ee9f04786db4f6f38619ace193e358242a72dc606ad81f3c4bc0ed8f1e28`

| Pair | Loss max Δ / limit | Grad-norm max Δ / limit | Result |
|---|---:|---:|---|
| L-M1-off / L-M1-on | 0.0500194728374 / 0.233478069305 | 8.3840970993 / 57.4342746735 | PASS |
| L-M2-off / L-M2-on | 0.0482786893845 / 0.233478069305 | 12.530714035 / 57.4342746735 | PASS |

The limits are twice the maximum observed stepwise delta over the six pairwise contrasts among four OFF calibration arms. Those contrasts share arms and are not independent samples.

| ON arm | Runtime roles seen | Start/enable markers |
|---|---|---:|
| L-M1-on | collector, sender | 6 |
| L-M2-on | collector, sender | 6 |

Runtime logs contain profiler `started` and `enabled` markers for both sender and collector roles, with the frozen 5-second window. The paired OFF logs contain no profiler activation markers.

| Arm | Manifest SHA-256 | Job-log SHA-256 | Resolved-argv SHA-256 |
|---|---|---|---|
| L-C1-off | `34a3696523f5f0cf179366beac570963e022952c15b98f0614f56ab5e5f3c3ec` | `2b6f673d12ca5220566cbb33e03ae05195184b8a335f206ea45075e09eb6cfeb` | `6e4146cff4d5cce6997c4aed995e19eb409a3dc80ec921bf7d2224f172c872a8` |
| L-C2-off | `b6d9eb4c9ec2629ca84a214df194bb71faec703428c0c8c44e2514c644d4fc84` | `5ec8300ad2ed1ed800055599cf4387ad89a3be61d0fa9577cbd32551b4364a3f` | `9aa69639c6e9041ef3e8a5c8d1e86178d4bd7ddda6a6412672c1d92a8980245b` |
| L-C3-off | `78297f757bb6cb18ca46f583147ea3559505f5f2e5948d22063dc898b578a04a` | `474d0fef3606e6cb741074daabc0cd0cb1ea57fd8414cf72497177e276ca241d` | `95912eeae67b5b8edf8f5a548dcee31ac9dd916b328dd0593b04b78dab7c3d7d` |
| L-C4-off | `d77f33fd756f614fa2c30c5bfd5a7e0d0780467e82ac39e620c291df686a3c7d` | `298a837e3cb92265d0cdad8acffb09e763ecd3cc7dc31ef4efb6d38f19d8fdb7` | `534ae402407cf5d99146a10ee0657d87e5425b3300c7f08dcf18a75d00463aea` |
| L-M1-off | `30fdcf7d8e2f351dff0c7125daae861a894e9eea61f56e707cc3d3cc86965673` | `e3d8ce4824597c954b39200558f4babd8b7f780962b0ce3f83591c4f34dec98e` | `6eef90a32d64f0567007a5a4e447ce0f4946838c207d5d9cb8b9d926da90a262` |
| L-M1-on | `eb8a717b764ca733bd1d1192cba3f7bb4a023d0af97f97934251fb6fac547174` | `7c8aa45f1ffdab4a9ecf7f9847a2a56118467c5fac80f3b7735af5afd2cd0a72` | `7763ed6d7dafc3e2fec5660b18683b4561a23c2e5077b1cce93f29872da1e2a6` |
| L-M2-on | `9704b8faa84e164eead7b52279505ac055abd5e75e937fadf19ccf7b064afa6d` | `3990f4581cfe9b39727933856ee2d9d7b1d561589a2daf63bb472c6c83662d30` | `1902ccb088768436bd4c58fd15f0baf7a642dfb234a7d0638f17edf07c7c7da7` |
| L-M2-off | `ff17ef336bfa373fd823b859847e2c42e35d832cbcb4ce661755f126d72a5685` | `08ea11d9676ba167afc36a808e275259c619f80d3e70dfda5ca9d2023658fb15` | `996d2f2bb9d8c0dd781421a2fe083974e0268588c5f84695b7fc6c8e2c70c558` |

Raw campaign root: `/root/autodl-tmp/task11-3090/formal/native-loss-927c5de-20260930`
Audit tool SHA-256: `eff5f46150985688d7e91918051f1029b6e66fb09f18951779afe4e20ccf3001`

Scope: Pass means only that this final-SHA native loss/grad supplement is within its frozen OFF/OFF envelope; it does not establish parameter equivalence, accuracy, C1, or overall C2 acceptance.

This is a local evidence replay. Raw jobs, model files, training stack, and Ray runtime remain at their original machine paths; this report does not establish a portable restore or independent backup.
