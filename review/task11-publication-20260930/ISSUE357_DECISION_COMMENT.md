### Task 11：请导师裁决三项验收口径

当前 [PR #378](https://github.com/redai-studio/Relax/pull/378) 为 Draft，头 `c2875a5` 的 CI 8/8 通过，产品代码固定于 `927c5de`。

1. **开销主指标。** 六对旧版 `perf/train_time` pilot 的点估计为 +0.417%，95% CI 上界为 +2.023%，结论是 **INCONCLUSIVE**。官方的 \<0.5% 应以 `perf/train_time` 还是 whole-job wall-clock 判定？确定后再固定最终产品版本、样本量、配对顺序与停止规则。
2. **平台实时性。** 已有阶段级 JSONL 定位与 rollout 级 TensorBoard 确认；两种输出没有共同的逐事件 ID，事件级延迟 **UNMEASURED**。本期是否接受现有 rollout 节奏？若不接受，请确认需要的上报时限和最小接口，再实现及重验。
3. **Attention/MoE 范围。** 当前只有 schema 预留，真机证据覆盖单机 dense DP4。本期是否接受该边界？若不接受，请指定必须采集的阶段及判据。

进展更新：`927c5de` 的两对 checkpoint 参数比较已从保留原件完成本地数值复算；独立八臂 native loss/grad 与 3090 overlap 均通过各自冻结门槛，后两者的公开输入已下载复算。[当前证据与限制](https://github.com/redai-studio/Relax/issues/357)见 Issue 正文。约 258 GiB 参数原件仍只在本机，第三方完整参数复算与独立备份未闭合。以上分项不能替代 C1 正式判定、平台实时性裁决或 Attention/MoE 验收。
