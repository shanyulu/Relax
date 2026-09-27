# Final-code score-consistency reconfirmation (2026-09-27 morning)

Environment note: the r5 attempt the same morning (`reward_consistency_20260927_final_r5`)
failed for a purely environmental reason — the container was rescheduled overnight to a
new IP (172.17.0.3 -> 172.17.0.5) and the platform proxy (`http_proxy=127.0.0.1:17892`,
`no_proxy` covering only 127.0.0.1/localhost) started hijacking the engine's internal
warmup HTTP calls to the container IP; SGLang's warmup loop timed out for 12 minutes
against the PROXY (the `127.0.0.1:17892` in that traceback is the proxy, not the engine)
and the server self-terminated. Bypassing the proxy returned `/get_model_info` in 3.7 ms.
The runs below were executed on a proxy-free Ray cluster (fresh head, workers without
the proxy env) — identical product code, no other change.

Producing code: product head `0481701` (PR head `f507d3b`). Machine: 4x RTX 4090,
driver 595.71.05, fresh Ray cluster session_2026-09-27_10-26-06.

| run | verdict | result |
| --- | --- | --- |
| `reward_consistency_20260927_final_r6` (208 s) | **PASS** | greedy verdicts identical across engines; official sampling (temp 0.1) **0/50** instability; parse gate independent; zero truncated replies; attribution covers both engines; exact elastic removal on scale-in |
| `sampling_divergence_20260927_final_r4` (196 s) | **PASS** | adversarial divergent-RNG-history (engine A 300 stochastic draws ahead of B before attribution) **0/50** flips; attribution covers both engines; exact elastic removal |

This closes the criterion-2 reconfirmation gap caused by the 2026-09-26 machine fault:
the pinned seed-contract evidence at `945741e` (greedy identical, stochastic 0/50,
adversarial 0/50) now has its final-code counterpart at `0481701` with the
fa3 attention-backend change in the serving path. Environment incident context for both
days is on the Task 11 evidence branch (`env_incident_20260926_evening/` and its
2026-09-27 re-entry records, including this proxy finding).
