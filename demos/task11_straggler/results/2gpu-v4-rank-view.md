# Rank × stage view (measured standalone demo)

Samples received: 8064/8064; collector errors / transport drops: 0/0.
Durations are per-rank medians in milliseconds; collective intervals can include peer wait.

| Case | Rank | Workload | Forward | Backward | Collective interval | Optimizer | Samples | Finding |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Control | 0 | 48 | 0.057 | 0.053 | 1.178 | 0.015 | 8/8 | no alert |
| Control | 1 | 48 | 0.056 | 0.054 | 1.179 | 0.015 | 8/8 | no alert |
| Extra forward | 0 | 48 | 0.056 | 0.054 | 1.223 | 0.015 | 8/8 | no alert |
| Extra forward | 1 | 48 | 0.102 | 0.054 | 1.177 | 0.015 | 8/8 | forward @ step 16 |
| Unequal workload | 0 | 48 | 0.057 | 0.054 | 1.194 | 0.015 | 8/8 | not comparable |
| Unequal workload | 1 | 96 | 0.062 | 0.072 | 1.170 | 0.015 | 8/8 | not comparable |
| Host stall | 0 | 48 | 0.056 | 0.054 | 7.109 | 0.015 | 8/8 | no alert |
| Host stall | 1 | 48 | 0.056 | 0.062 | 7.184 | 0.015 | 8/8 | no alert |

The extra-forward case identifies a measured rank/stage slowdown; it does not identify a hardware fault. The unequal-workload case is excluded from peer comparison. No MetricsService integration or end-to-end alert latency is claimed here.
