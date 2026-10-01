### Task 4：请确认合入边界（PR #370，当前头 `da4acbb`；CI 8/8）

1. **Task 3 对接路线。** 官方将 Task 4 标为依赖 Task 3。目前 [#347](https://github.com/redai-studio/Relax/pull/347)、[#356](https://github.com/redai-studio/Relax/pull/356)、[#368](https://github.com/redai-studio/Relax/pull/368)、[#381](https://github.com/redai-studio/Relax/pull/381) 均未合入，且与 #370 在 `relax/components/genrm.py`、`relax/distributed/ray/genrm.py` 等文件重叠。请确定本期采用哪条统一 inference 路线，以及 #370 是先按单 Gateway 适配边界独立合入，还是在选定路线后对接并重验。现有证据不覆盖跨 Gateway 或 direct client 的 drain lease。
2. **工件归属。** 建议保留 `demos/task4_genrm` 的验收 driver 与证据索引，便于库内审查。若要求迁往 evidence 分支，请指出移动范围；原始证据和不可变链接会保留。
3. **验收规模。** 4×RTX 4090、Qwen3-0.6B 是否满足本期生命周期、路由和评分契约验收？若需要更大模型或集群，请给出具体判据。
4. **内容确定性采样。** `temperature > 0` 且调用方未指定 `sampling_seed` 时，当前实现由模型、实际输入 token 和有效采样参数派生 seed；相同内容的独立调用也复用随机流。请确认是否接受。若要求重复调用保持随机多样性，需要先确定请求身份／seed 契约，再改产品并重验评分。

当前 [PR #370](https://github.com/redai-studio/Relax/pull/370) 还需正式 review。若裁决不要求代码变更，保留当前头；若要求对接或语义修改，仅提交被指定的最小增量并重新走受影响的验证与 CI。
