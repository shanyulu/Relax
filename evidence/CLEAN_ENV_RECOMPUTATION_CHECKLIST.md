# Clean-environment recomputation checklist (pre-merge)

Purpose: a maintainer with no access to this machine can recompute the key
claims from public artifacts only. Every item lists inputs, command, and
expected output. Anything not recomputable this way is labeled as such in
EVIDENCE.md rather than claimed.

## 0. Pins

- Product (Task 11): `e961661bbdf662016a658d0fc2283d200a899a96`
- Product (Task 4): `0481701` (PR #370 head `5b512d0` is docs-only on top)
- Evidence branch: `f9976f8f4175454d7bcce66a36c0d63793869833` (protocol) and the
  campaign commit that carries `gpu_campaign/abba-e961661-run1`

## 1. Artifact integrity (no GPU, ~1 min)

```
sha256sum demos/task4_genrm/results/train_continuity_20260925_r5/raw_job_driver.log
```
Expected: `feb23ecc80d3ce7382cefd68ca32aea20c5c26f3057978a272c0b40f44dfec78`
(recorded alongside as `raw_job_driver.log.sha256`).

## 2. Machine-generated reports regenerate bit-for-bit (no GPU, ~1 min)

```
python3 demos/task4_genrm/results/train_continuity_20260925_r5/reanalyze_three_timelines_v2.py
python3 demos/task4_genrm/results/train_continuity_20260925_r5/render_reanalysis_v2.py
```
Expected: `reanalysis_v2.json` / `REANALYSIS_V2.md` byte-identical to the
archived copies (pure log parsing, no timestamps embedded).

## 3. Targeted test suite (no GPU, ~3 min)

```
pip install -r requirements.txt
pytest tests/ -p ci_block_megatron -q <straggler suite paths>
```
Expected: 374 passed / 2 environment-gated skips at `e961661`.

## 4. Gated analyzer verdict reproduces (no GPU, ~1 min)

```
python3 evidence/analyze_c1.py --campaign evidence/gpu_campaign/abba-e961661-run1 \
    --expected-steps 48 --out /tmp/verdict.json
```
Expected: deterministic verdict (fixed bootstrap seed 20260927); the archived
`verdict.json` and the recomputed one must agree on every gate and on the
point estimate. The bootstrap CI is seed-pinned, so agreement is exact.

## 5. Full campaign recompute (4× RTX 4090, ~1.2 h, optional)

Inputs are public: HF model snapshot `Qwen/Qwen3-0.6B` + the dataset JSONL
committed under `scripts/training/sft/data/`. Run the archived driver
(`evidence/gpu_campaign/abba-e961661-run1/driver.py` or the recorded command)
at the pinned product SHA with `SAVE=0`. Expected: verdict category
(PASS / NOT PASS / INCONCLUSIVE) unchanged; point estimate within the
archived bootstrap CI. This is the only item that needs GPUs.

## Items NOT recomputable from public artifacts (labeled as such)

- Per-sample rollout JSONLs (rotated away on the runner; log lines + SHA256
  are the durable record)
- r5/r6 engine-attribution runs (runner-local HF cache paths; commands and
  raw logs archived instead)
