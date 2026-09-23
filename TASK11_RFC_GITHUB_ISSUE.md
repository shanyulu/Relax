# 【No.11】Relax Straggler 分析能力建设 - RFC

提案人：@shanyulu · 导师：@Lemon-412 · 状态：待评审

给训练补一份持续更新的 **rank × 阶段耗时**：看见哪张卡、哪个阶段持续变慢，并保留工作量和对照组。方案是抽样记录 CUDA Event、后台读数上报；不改训练调度，不凭耗时直接判定硬件故障。**当前 demo 是独立机制验证，不是 Relax 集成或官方验收结果。**

![训练记录、后台回收、平台比较的边界](https://raw.githubusercontent.com/shanyulu/Relax/codex/rfc-visuals/demos/task11_straggler/results/cover.jpg)

## 做什么

| 首期交付 | 边界 |
| --- | --- |
| forward、backward、optimizer、通信区间耗时 | Event 区间可能包含等待，不等于纯计算或链路耗时 |
| rank、step、工作量与可用的 PP 调度位置 | PP>1 先报 rank 本地累计；attention/MoE 预留开关 |
| 持续异常、对照组、覆盖率、缺报与上报延迟 | 工作量不等或没有等价 peer，报告“证据不足” |

范围按[导师公开答复](https://github.com/redai-studio/Relax/issues/334#issuecomment-5757676464)：只观测，不踢卡、不调整训练；阈值可配置，先用可用硬件上的 recipe 验证。

## 怎么接入

现有 `Timer` 看阶段总时长，`TrainProfiler` 做短时分析，两者保持原用途。持续采集分三处接入，**尚未集成到 Relax**：

| 位置 | 方案与约束 |
| --- | --- |
| MCore schedule | 分开记录 forward/backward，附 step/PP 上下文；外包 `train_one_step` 无法拆开 `forward_backward_func` |
| Relax optimizer / 通信挂点 | optimizer 在调用边界计时；通信先用 trace 核实 stream 和完成边界 |
| 后台 → MetricsService | 查询已完成 Event，批量发送；现有上报路径含同步 HTTP，不能放在训练线程 |

默认关闭；开启后仅采样步记录 Event，不新增计时同步或训练 collective。Event 池、待处理窗口、发送队列均有上限，满额丢样并计数。平台迟到数据的缓存与清理在接入时验证。

告警只比较**同分片、同阶段、工作量可比**的 rank；缺报、乱序和不可比样本打断连续异常判断。对端计算慢也会拉长本卡通信等待，因此报告异常区间，不直接归因网络。组内 `no alert` 也不能排除所有卡同时变慢。

<details>
<summary>采集流程与告警规则</summary>

![采样步记录 Event，后台查询完成后回收](https://raw.githubusercontent.com/shanyulu/Relax/codex/rfc-visuals/demos/task11_straggler/results/async-sampling.jpg)

![先核对等价副本和工作量，再判断持续异常](https://raw.githubusercontent.com/shanyulu/Relax/codex/rfc-visuals/demos/task11_straggler/results/diagnosis.jpg)

</details>

## Demo 与未验证项

下图由双卡 demo 的逐样本数据生成，不是平台效果稿。

![实际 rank × 阶段结果视图](https://raw.githubusercontent.com/shanyulu/Relax/codex/rfc-visuals/demos/task11_straggler/results/2gpu-v4-rank-view.png)

| 已验证 | 结果与限制 |
| --- | --- |
| [v4 双卡实验](https://github.com/shanyulu/Relax/tree/7718e036c7144b68a01a8b608a4b463eb8e16ddd/demos/task11_straggler) | 两轮开销中位数 0.116% / 0.146%；off/off 对照仍有系统偏移，不能据此认定 <0.5% |
| 采集与诊断 | 两轮各接收 8064/8064 样本；最终 loss、参数一致；约 1.8× 前向变慢均在 step 16 定位 rank 1 |
| [当前版本](https://github.com/shanyulu/Relax/tree/codex/rfc-visuals/demos/task11_straggler) | 19 项测试通过；生命周期 smoke 单对开销 0.527%；host stall 出现 backward 区间告警，不能据此认定 backward 是根因 |
| [恢复场景交互回放（下载后打开）](https://github.com/shanyulu/Relax/blob/codex/rfc-visuals/demos/task11_straggler/results/2gpu-recovery-demo.html) · [预览图](https://github.com/shanyulu/Relax/blob/codex/rfc-visuals/demos/task11_straggler/results/2gpu-recovery-demo-preview.jpg) | 224/224 样本接收；rank 1 只在中段变慢，随后回到 peer 范围；丢一条报告的按钮是接收端反事实回放 |

![Task 11 交互回放预览：异常、恢复与 rank × 阶段轨迹](https://raw.githubusercontent.com/shanyulu/Relax/codex/rfc-visuals/demos/task11_straggler/results/2gpu-recovery-demo-preview.jpg)

**尚未完成官方验收。** 真实 recipe、MetricsService 和通算 overlap 均未验证。当前故障隔离只覆盖启动后的后台读数与传输；初始化和 Event.record 异常仍会抛出，不能承诺所有观测故障都不影响训练。

<details>
<summary>实验图、复现方法与完整记录</summary>

![两轮双卡实验；诊断与样本面板展示 Run 1](https://raw.githubusercontent.com/shanyulu/Relax/codex/rfc-visuals/demos/task11_straggler/results/2gpu-v4-comparison.png)

v4 每轮含 4 组 8000-step off/on 与 4 组 off/off，每次约 10.3–10.4 秒，每 8 步采样。置信区间、对照偏移、版本对应关系和历史试次见[证据记录](https://github.com/shanyulu/Relax/blob/codex/rfc-visuals/demos/task11_straggler/EVIDENCE.md)。v4 性能数据不代表后续修订版本。

</details>

## 如何验收

| 官方要求 | 检查方法 |
| --- | --- |
| 整体开销 <0.5% | 固定 recipe、工作量、采样和上报配置，多轮开关对照；计入后台与平台成本，同时报告覆盖率与置信区间 |
| 精度、loss、overlap 不受影响 | 对照 loss、参数和训练进度；短时 trace 检查已有通算 overlap，容差事先约定 |
| 实时上报、便于定位 | 展示 rank/阶段/对照组、缺报率和端到端检测延迟；注入计算、host、通信异常，测试检出与误报 |

判定规则首期固定为：同 cohort、同 stage set、工作量差 ≤5%，且连续两个采样窗口满足 `observed / peer ≥ ratio` 与 `observed − peer ≥ absolute_ms`；缺报、乱序、stage 不一致均进入 `uncertain`，不进入持续异常计数。默认值只用于 demo，接入时由 recipe 校准。

先验证 MCore 挂点，再接 MetricsService，最后跑完整 recipe 对照。请导师确认**首期 recipe 与 PP 配置，以及挂点和平台接入范围**。

参考：[官方 Task 11](https://github.com/redai-studio/community/blob/main/contributor-program/2026-cohort-2/official-task.md) · [导师背景补充](https://github.com/redai-studio/Relax/issues/334#issuecomment-5757682517) · [代码基线](https://github.com/redai-studio/Relax/blob/0651812093e3cd730302709b3db35ce0bb199e4b/relax/backends/megatron/model.py#L1449)
