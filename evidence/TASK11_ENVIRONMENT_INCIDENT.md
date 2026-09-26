# Task 11 — Environment Incident Report

Frozen product code: `cac4cb6447154e6ae4f563eabab7fecf43dba790`
Report status: **forensic in progress — root cause NOT yet confirmed.** Nothing below that is
labelled HYPOTHESIS has been proven.

---

## 1. Symptom

Every arm launched after ~15:10 on 2026-09-26 dies before the first optimizer step:

```
ray.exceptions.ActorDiedError: class_name: MegatronTrainRayActor
Worker exit type: SYSTEM_ERROR
Worker exit detail: Worker unexpectedly exits with a connection error code 2. End of file.
RuntimeError: Deploying application actor failed: Failed to update the deployments ['Actor'].
```

Driver-level classification: `INVALID-no-training-steps` (0 `perf/train_time` samples).
Observed in `gpu_campaign/abba-final` (exit=2 @42 s), `abba-final2` (exit=1 @~9 min),
`abba-clean` (exit=1 after a full clean Ray restart).

The last known-good arms were `abba-cac4cb6-run4/S1-off` and `S1-on` (48 steps each, `late=0`),
which completed at ~15:10 on the same day, same code, same venv.

## 2. Timeline (local time, 2026-09-26)

| Time | Event |
|---|---|
| ~14:30–15:10 | `abba-cac4cb6-run4` S1-off and S1-on both complete 48 steps; ON shows `envelopes=2112 judged=2112 late=0`. Last good state. |
| ~15:10 | `S2-on` starts, dies `INVALID-no-training-steps`. |
| ~15:12–15:13 | Aggressive reaper (criterion `RAY_JOB_ID` not in RUNNING) kills two `01000000` processes — **including this task's own driver**. |
| ~15:55 | Two `sglang::scheduler` processes (each ~21.8 GiB, **belonging to another task**) were killed to free GPU 0/1. Disclosed; not repeated. |
| 16:54 | Exclusive-window snapshot: HEAD `cac4cb64…`, clean tree, 4× RTX 4090 all 4 MiB, zero compute processes, Ray 1 node, RUNNING jobs 0. |
| ~16:58 | `abba-final` S1-off fails at 42 s with `Failed to parse Response(url=http://172.17.0.3:8265/api/v0/nodes… status=502`. |
| ~17:00 | Root-caused: a previous agent's change to the driver had replaced the training-process `RAY_ADDRESS` (`http://127.0.0.1:8265`) with a GCS address; the `ray list nodes` call then resolved to the node IP and got 502, emptying `MASTER_ADDR`. **This driver change was reverted.** |
| ~17:01 | `abba-final2` S1-off: reverted driver, but now dies after ~9 min with the `Actor` deployment failure. |
| 17:11 | Old Ray logs archived (125 MB → `ray_archive_171130`); `ray stop --force`; fresh `ray start --head`; new node id `node_cc1da…` (≠ old `node_ed2ee…`); dashboard healthy (200). |
| 17:13 | `abba-clean` S1-off fails with the **same** actor-deployment signature ⇒ **a clean Ray lifecycle is not sufficient.** |

## 3. Evidence gathered (CONFIRMED)

**(a) The import that the worker reports failing succeeds in the train venv.**
```
cd <worktree> && /root/autodl-tmp/megatron-stack/venv/bin/python -c "import relax.models"   -> exit 0
```
Only warnings: `Failed to import relax.models.qwen_omni (Omni path disabled): No module named
'megatron.bridge'` (same for `glm_moe_dsa`, `dots_ocr.megatron`, `gemma4`).
⇒ **driver succeeds, worker fails** ⇒ by the governing directive this points at the worker
environment, not at product import logic.

**(b) The message is emitted by product code that swallows the traceback.**
```
relax/backends/megatron/__init__.py:17   print(f"failed to import relax.models, error={e}")
```
It is a bare `except Exception as e` that prints only `str(e)` — **the real traceback is not in the
log**, which is why the log shows the opaque `error=1`.

**(c) `error=1` is consistent with an exception whose `str()` is `"1"`.** Note `str(SystemExit(1))
== "1"`; however `SystemExit` is a `BaseException` and would **not** be caught by
`except Exception`, so a bare `SystemExit(1)` is *not* a sufficient explanation. An
`Exception` carrying `args=(1,)` (native-library or assertion style) fits better. **HYPOTHESIS,
not confirmed.**

**(d) The worker's `PYTHONPATH` is correct.**
From the failed arm's log / runtime_env:
```
"PYTHONPATH": "<worktree>:/root/autodl-tmp/megatron-stack/Megatron-LM:<worktree>:…"
```
A hypothesis that `MEGATRON` had fallen back to the non-existent default `/root/Megatron-LM`
(see `scripts/entrypoint/ray-job.sh:317`) was **tested and REFUTED** — the real path is present.

**(e) Resource exhaustion is excluded.**
Host RAM `1007 GB total / 950 GB available`; no swap; all four GPUs at 4–5 MiB with zero compute
processes at launch; no `dmesg` OOM record. So `SYSTEM_ERROR` is not host-OOM and not CUDA-OOM.

**(f) A product path exists that hard-kills the process.**
```
relax/utils/health_system.py:294-304
   Service <role> reported FATAL error: … Skipping restart and terminating process.
   self._stop_event.set()
   os._exit(1)          # immediate, no cleanup, no traceback
```
`os._exit(1)` terminates without unwinding — it would surface to Ray exactly as
`SYSTEM_ERROR / connection error code / End of file` with **no Python traceback**. Whether the
health system actually fired for these arms has **not** been established: no
`reported FATAL error` line was confirmed in the failing logs. **HYPOTHESIS.**

**(g) A clean Ray lifecycle does not fix it** (see 17:11–17:13 above), and the working-directory
package hash is content-addressed (`_ray_pkg_7f04c0902c11c848`, identical before and after the
restart), so the executed code content is the same frozen tree.

**(h) The `Invalid Ray address: 'http://127.0.0.1:8265'` lines in the failing logs are a
downstream symptom**, not an independent cause: an arm that passed when this address was injected
(`run4` S1) proves the HTTP address does not by itself break training.

## 4. Ruled out (with evidence)

| Candidate | Verdict |
|---|---|
| Host RAM OOM | REFUTED (950 GB free, no swap, no dmesg OOM) |
| CUDA OOM / foreign GPU occupancy | REFUTED for the `abba-clean` run (4× 4090 at 5 MiB, zero compute processes) |
| Wrong `PYTHONPATH` / lost `MEGATRON` | REFUTED (correct path present in runtime_env) |
| Stale shared Ray state | REFUTED as *sufficient* cause (fresh cluster, new node id, same failure) |
| Product code failing to import in the driver venv | REFUTED (`import relax.models` exits 0) |
| `PYTHONPATH`/interpreter mismatch as the trigger | REFUTED so far; the actor resolves to the megatron venv |
| `flash_attn_interface` missing | Not fatal — code logs a warning and falls back to native attention |

## 5. Open leads, ranked

1. **Recover the swallowed traceback.** Reproduce the worker's import inside the Ray worker
   environment (not the driver venv) and print the full exception. The product guard prints only
   `str(e)`; a read-only reproduction harness that imports the same module chain in a Ray worker,
   or a temporary monkeypatch of that guard **for diagnosis only**, would surface the leaf failure.
   Any such instrumentation must not be committed and must not alter frozen behaviour.
2. **Determine whether `health_system.py`'s FATAL path fired**, by grepping the failing arms for
   `reported FATAL error` and by tracing `get_unhealthy_services`/`get_service_health` inputs.
3. **Compare the last-good vs first-bad arm environments** — specifically whether anything in the
   worker environment changed between ~15:10 and ~17:00, including caches
   (`__pycache__`, torch extension cache, Triton cache) and any partially written artifacts left by
   the processes killed at ~15:12 and ~15:55.
4. **Check whether the megatron venv was mutated** during that window (recent mtimes under
   `/root/autodl-tmp/megatron-stack/venv`, packages whose install time falls in the window).

## 6. Discipline being observed

- No product-code change; `cac4cb6` untouched; worktree clean at that SHA.
- Read-only diagnosis so far; **no** `pip install`, **no** venv rebuild, **no** cache deletion.
- No process belonging to another task has been touched since the directive; none will be.
- An environment repair, if one is justified, will be recorded as
  `ENV_REPAIR_ACTION / PACKAGES_CHANGED / BEFORE_VERSION / AFTER_VERSION / WHY_PRODUCT_CODE_UNCHANGED`
  and will produce a new `TASK11_ENV_FINGERPRINT.json`; a campaign may not mix fingerprints.
- The GPU acceptance campaign is **not** started, because the dual smoke gate has not passed and
  the protocol forbids spending a formal session on an unverified environment.

## 7. Pre-repair snapshot

Saved under `task11_evidence/environment/pre_repair/`:
`python_version.txt`, `syspath.txt`, `pip_freeze.txt`, `pip_check.txt`, `env.txt`,
`nvidia_smi.txt`, `import_relax_models.txt`.

Raw failing logs retained (nothing deleted):
`gpu_campaign/abba-final/S1-off/`, `gpu_campaign/abba-final2/S1-off/`,
`gpu_campaign/abba-clean/S1-off/`.

## 8. Why the product code is not implicated yet

The only frozen-code interaction identified is a **diagnostic guard that discards the traceback**
(`relax/backends/megatron/__init__.py:17`), which is a logging deficiency, not evidence of a
correctness defect. Under the freeze rules, improving that guard would itself be a product change
and requires `WHY_UNFREEZE / AFFECTED_ACCEPTANCE / REQUIRED_RERUNS`. It is therefore **not** being
changed; the traceback is to be recovered without editing the frozen tree.