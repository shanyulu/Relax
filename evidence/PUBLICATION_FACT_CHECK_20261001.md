# Task 11 发布口径核对（2026-10-01）

产品固定为 `927c5de2f5a8f307cad0c87f2c7eb2b78262334d`。本记录纠正文档解释，不改冻结协议、原始数据或 verdict。

- 参数复算每对 182/182 entries 包含 13 个非空浮点 storage 组：10 个 BF16 模型组和 3 个 FP32 optimizer 组；另 169 个是零元素 TE 占位。实验单位为两对 OFF/ON，entries 不是独立样本。
- loss 最大差 `0.046285/0.030037` 与 grad norm 最大差 `7.94949/5.50596` 来自 `927c5de` 参数实验 P-M1/P-M2。该实验未提前冻结 loss/grad 容差，保持 `UNSCORED`。依据为 `PARAMETER_COVERAGE_REVIEW_20260930.md`。
- 新 L-M 系列 loss/grad 是独立补验：四个 OFF 校准臂、两对测量臂，各 48 步。其 PASS 仅限自身冻结包络，不改写旧 P-M 旁证。
- C1 pilot 的 +0.417% 与 95% CI 上界 +2.023% 使用 `perf/train_time`；whole-job wall-clock 尚未获选为正式主指标。
- native-loss SVG 表示最大绝对差除以冻结容差的条形长度，不是置信区间或统计误差条。
- observer-only 运行的尾窗及 pending readouts 未取得终态 accounting，不能发布最终零丢弃结论。

参数完整原件约 258 GiB，仍仅本地保留。公开结果、哈希与小证据包不能替代这些原件的独立存储或第三方完整参数复算。
