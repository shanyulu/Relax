## Task 11 — observer overhead per pair (whole-run wall, AB/BA balanced)

| pair | order | OFF wall (s) | ON wall (s) | Δ (s) | overhead % | tokens equal | steps equal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S1 | A->B | 307.9 | 309.6 | +1.6 | +0.54% | True | True |
| S2 | B->A | 308.1 | 310.3 | +2.2 | +0.72% | True | True |
| S3 | A->B | 307.6 | 306.5 | -1.1 | -0.35% | True | True |
| S4 | B->A | 307.8 | 308.9 | +1.1 | +0.34% | True | True |
| S5 | A->B | 307.9 | 310.6 | +2.7 | +0.86% | True | True |
| S6 | B->A | 313.5 | 308.1 | -5.4 | -1.72% | True | True |

Mean overhead **+0.07%**, bootstrap 95% CI **[-0.72%, +0.67%]** (6 pairs, 10k pair-level resamples, seed 20260927).

```mermaid
xychart-beta

    title "Per-pair observer overhead (% of whole-run wall)"
    bar [
0.54, 0.72, -0.35, 0.34, 0.86, -1.72
    ]
```
