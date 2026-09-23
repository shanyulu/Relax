# Rank × stage view (measured standalone demo)

Samples received: 3664/3664; collector/transport errors: 0/0.
Durations are per-rank medians in milliseconds; collective intervals can include peer wait.

| Case | Rank | Workload | Forward | Backward | Collective interval | Optimizer | Samples | Finding |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Control | 0 | 48 | 0.056 | 0.053 | 1.183 | 0.014 | 8/8 | no alert |
| Control | 1 | 48 | 0.056 | 0.054 | 1.183 | 0.015 | 8/8 | no alert |
| Extra forward | 0 | 48 | 0.056 | 0.053 | 1.226 | 0.015 | 8/8 | no alert |
| Extra forward | 1 | 48 | 0.103 | 0.054 | 1.180 | 0.014 | 8/8 | forward @ step 16 |
| Unequal workload | 0 | 48 | 0.056 | 0.053 | 1.194 | 0.015 | 8/8 | not comparable |
| Unequal workload | 1 | 96 | 0.062 | 0.070 | 1.170 | 0.014 | 8/8 | not comparable |
| Host stall | 0 | 48 | 0.056 | 0.053 | 7.131 | 0.015 | 8/8 | no alert |
| Host stall | 1 | 48 | 0.057 | 0.054 | 7.131 | 0.015 | 8/8 | no alert |

The extra-forward case identifies a measured rank/stage slowdown; it does not identify a hardware fault. The unequal-workload case is excluded from peer comparison. No MetricsService integration or end-to-end alert latency is claimed here.
