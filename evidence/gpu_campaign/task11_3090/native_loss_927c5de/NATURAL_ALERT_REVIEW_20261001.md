# Observer-only straggler detections in the native loss arms

**Finding.** The saved verdict streams contain seven confirmed detections across two observer-enabled `927c5de` runs with no configured delay injection. All seven used complete, workload-comparable DP4 cohorts. Six have a later `within_tolerance` recovery verdict. The seventh (M1, rank 2 `forward-compute`) was still active in the saved status snapshot. These are measured anomalies, not proven hardware faults and not false positives.

![Saved detections, recoveries, and unclosed raw-tail candidates](NATURAL_ALERT_REVIEW_20261001.svg)

## Scope and evidence

Both arms used product `927c5de2f5a8f307cad0c87f2c7eb2b78262334d`, four GPUs, 48 steps, seed 1234, the same dataset and recipe. The manifests set `RELAX_STRAGGLER_ENABLE=1`, 5-second windows and two warmup windows. Their launch arguments contain no slowdown injector; the training logs report `error_injection_rate=0` and no fault-injector delay/rank configuration. These are observer-only runs. The raw files remain local; this report does not make them publicly downloadable.

| Arm / run              | Envelope JSONL | Saved verdict JSONL | Saved verdicts                          | Raw envelope SHA-256                                               | Verdict SHA-256                                                    |
| ---------------------- | -------------: | ------------------: | --------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------ |
| `L-M1-on` / `0c000000` |          2,112 |                 145 | 1 confirmed, 144 uncertain              | `685490a3157bb6ad06491edf7a1ff6c48ef2b270dfbdd66bcd046870fa13abce` | `6bca939dc35ea7032c774fff3be533662e1aaef8b2d2769a67bb275f7fb21379` |
| `L-M2-on` / `0d000000` |          1,899 |                 139 | 6 confirmed, 6 recovered, 127 uncertain | `c80ab498b02e16c5f6850d7c15a378169e614ef3d4629fb33c628ff81a7adefd` | `faeffbe92512593a8a9e30d880159b3a18dda67ebf4c9109ee5ce77bfec2c073` |

All 4,011 envelope lines parse and have unique `(rank, seq, stage)` identities. They all carry device timing and workload fields; none is a barrier sample. In the event windows, all four ranks reported and every target rank had all three peers in its comparable class. Each rank contributed four or five samples. Token-volume differences stayed within ±1.25%; sequence-count and microbatch-count differences were zero. Thus the seven saved detections are not explained by the measured work-volume differences.

Reproduction command (requires local raw artifacts and a clean checkout of the pinned product):

```bash
python evidence/tools/replay_native_loss_alerts_20261001.py \
  --product-root /root/autodl-tmp/relax-work/task11-c2-927c5de \
  --measurement-root /root/autodl-tmp/task11-3090/formal/native-loss-927c5de-20260930/measurement
```

The script validates the product SHA and no-injection settings in each job log, checks the raw-file hashes and envelope identities, replays through the pinned detector, and prints the saved and replay-only results as JSON. It writes no files. Its source and this report are committed together; the commit hash identifies the exact calculation used here.

## The seven saved detections

Ratios compare the detected rank with the detector's effective peer reference. `Host` is observed wall time; `device` is the CUDA-event interval. Recovery is the next saved `recovered / within_tolerance` verdict for that rank and stage.

| Arm | Window | Rank / stage          | Samples: rank; peers | Host ms; ratio                | Device ms; ratio              | Work delta: tokens / sequences / microbatches | Streak / classification       | Saved recovery                                    |
| --- | -----: | --------------------- | -------------------- | ----------------------------- | ----------------------------- | --------------------------------------------- | ----------------------------- | ------------------------------------------------- |
| M1  |     16 | r2 `forward-compute`  | 4; r0:5, r1:4, r3:4  | 130.510 / 113.993; **1.145×** | 128.257 / 111.683; **1.148×** | −0.039% / 0% / 0%                             | 3 windows; `gpu_stream_stall` | None in saved verdicts; active in captured status |
| M2  |     11 | r1 `forward-compute`  | 4; r0/r2/r3:4        | 148.557 / 115.012; **1.292×** | 146.330 / 112.712; **1.298×** | +0.325% / 0% / 0%                             | 3; `gpu_stream_stall`         | w13                                               |
| M2  |     11 | r2 `forward-compute`  | 4; r0/r1/r3:4        | 140.503 / 115.012; **1.222×** | 138.647 / 112.712; **1.230×** | −0.324% / 0% / 0%                             | 3; `gpu_stream_stall`         | w14                                               |
| M2  |     11 | r3 `forward-compute`  | 4; r0/r1/r2:4        | 149.768 / 115.012; **1.302×** | 147.659 / 112.712; **1.310×** | −0.566% / 0% / 0%                             | 3; `gpu_stream_stall`         | w12                                               |
| M2  |     11 | r2 `forward-backward` | 4; r0/r1/r3:4        | 249.073 / 230.622; **1.080×** | 653.503 / 641.834; **1.018×** | −0.324% / 0% / 0%                             | 3; `host_only_stall`          | w12                                               |
| M2  |     11 | r3 `forward-backward` | 4; r0/r1/r2:4        | 259.624 / 230.622; **1.126×** | 652.705 / 641.834; **1.017×** | −0.566% / 0% / 0%                             | 3; `host_only_stall`          | w12                                               |
| M2  |     15 | r3 `forward-compute`  | 5; r0/r1/r2:5        | 148.536 / 115.322; **1.288×** | 146.143 / 113.020; **1.293×** | −1.242% / 0% / 0%                             | 3; `gpu_stream_stall`         | w16                                               |

The three simultaneous `forward-compute` detections in M2 window 11 compare ranks 1–3 with rank 0, the fastest peer in that window. The evidence supports a same-window timing separation at similar measured work; it cannot distinguish a shared slowdown on ranks 1–3 from rank 0 being unusually fast. The two `forward-backward` detections have host ratios of 1.080× and 1.126× but device ratios of only 1.018× and 1.017×, matching the detector's `host_only_stall` classification. This shows a host-visible differential without a comparable CUDA-event differential; it does not identify its cause.

`gpu_stream_stall` means both host and CUDA-event timings crossed the detector thresholds. It does not mean GPU utilization, saturation, or a hardware fault was measured. No per-rank clock, utilization, thermal, host scheduling, storage, or fabric telemetry in these artifacts identifies a physical cause. Workload imbalance is unsupported by the recorded token/sequence/microbatch data; injector causality is unsupported because no injector was configured. The physical source of the measured timing differences remains unknown.

## Final-window completeness and drop accounting

The saved verdict files are not a complete adjudication of all raw envelopes. Both `runtime_status.json` snapshots say `closed=false` and retain two open windows; the M1 observer snapshot has six pending readouts and M2 has one. The snapshots were written before job completion. M1's collector snapshot records 1,856 envelopes and 2,001 flushed lines, while the later raw files contain 2,112 envelopes plus 145 verdicts (2,257 lines). M2's line counts agree (1,899 + 139 = 2,038), but its status also retains two open windows and one pending readout. Consequently, the stored `stragglers_reported` totals (1 and 6) describe saved verdicts, not a proven final count after draining and closing every window.

For diagnosis, the complete raw envelope streams were replayed through the frozen `927c5de` detector with the recorded 5-second window, two-window warmup, 5% work tolerance, 5 ms floor, and three-window persistence; the remaining windows were then explicitly flushed. This reproduced all seven saved detections and yielded five additional threshold crossings in raw tail windows absent from the saved verdict streams:

| Arm | Replay-only tail window | Rank / stage          | Host ratio | Replay outcome                                         |
| --- | ----------------------: | --------------------- | ---------: | ------------------------------------------------------ |
| M1  |                      17 | r3 `forward-compute`  |     1.103× | additional candidate; no saved runtime verdict         |
| M1  |                      18 | r2 `forward-backward` |     1.067× | additional candidate; no saved runtime verdict         |
| M2  |                      17 | r2 `forward-compute`  |     1.207× | additional candidate; recovered in replay at w18       |
| M2  |                      17 | r1 `all-grads-sync`   |     1.129× | additional candidate; remained active at end of replay |
| M2  |                      17 | r2 `forward-backward` |     1.080× | additional candidate; recovered in replay at w18       |

These five are **offline replay results**, not detections recorded by the live collector. They must not be added to the seven saved verdicts as confirmed runtime alerts; they do show that final-window drain/flush evidence is missing. The M1 rank-2 saved alert has no recovery verdict, and its snapshot still lists it active. Since the run ended without a final closed status, its behavior at actual termination is not established. At offline replay end, M1 had three active keys (rank 2 `forward-compute`, rank 3 `forward-compute`, rank 2 `forward-backward`); M2 had one (rank 1 `all-grads-sync`).

The status snapshots record zero sender queue-full drops, send errors, duplicate/late/invalid packets, invalid timing samples, collector write errors, pending-line drops, and close errors. Those are snapshot counters, not a post-teardown accounting. For M1, the envelope file continued growing after the collector status write. Therefore **no drop was recorded in the available snapshots**, but these artifacts do not prove a final zero-drop count after shutdown.

## Conclusion

The seven persisted alerts have complete cohort coverage, comparable measured work, device timing, and three-window persistence. The compute-stage alerts are supported as measured host-and-device timing outliers; the two `forward-backward` alerts are supported as host-only timing outliers. The evidence does not establish why the differences occurred. Six saved alerts later recovered within tolerance; one saved alert had no recovery in the captured status. Five more crossings appear only when the raw tail is replayed and flushed. Because the final collector state was not captured, treat seven as the count in the saved verdict files—not the complete alert count of either run.
