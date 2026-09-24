# 【No.11】Relax Straggler 分析能力建设 - RFC

提案人：@shanyulu · 导师：@Lemon-412 · 状态：待评审

目标是在训练过程中持续看到每个 rank 的阶段耗时，并指出持续变慢发生在哪个阶段。采集时保留工作量、并行位置和缺报信息，避免把数据量差异或等待同伴误报为坏卡。当前双卡 demo 验证了采集与判定机制；Relax recipe 上的开销和精度仍待实测。

![训练记录、后台回收、平台比较的边界](https://raw.githubusercontent.com/shanyulu/Relax/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task11_straggler/results/cover.jpg)

## 做什么

| 首期交付                                   | 边界                                            |
| ------------------------------------------ | ----------------------------------------------- |
| forward、backward、optimizer、通信区间耗时 | Event 区间可能包含等待，不等于纯计算或链路耗时  |
| rank、step、工作量与可用的 PP 调度位置     | PP>1 先报 rank 本地累计；attention/MoE 预留开关 |
| 持续异常、对照组、覆盖率、缺报与上报延迟   | 工作量不等或没有等价 peer，报告“证据不足”       |

范围按[导师公开答复](https://github.com/redai-studio/Relax/issues/334#issuecomment-5757676464)：只观测，不踢卡、不调整训练；阈值可配置，先用可用硬件上的 recipe 验证。

## 怎么接入

现有 `Timer` 看阶段总时长，`TrainProfiler` 做短时分析，两者保持原用途。Relax 当前在三处把 `config.timers` 置 None（`relax/backends/megatron/model.py` 的 optimizer 配置、评估与训练路径）；向该接口注入非阻塞 timer 即可激活 Megatron 既有调用点；#363 走的正是这条路线（自报 22 处调用点、不改 Megatron 源码），但区间粒度受既有调用点限制。外包 `train_one_step` 则拆不开 `forward_backward_func`。因此接入第一步是用短 trace 核定既有调用点对所需边界的实际覆盖：够用的直接复用 timer 接口，拆不开 forward/backward 的位置才改 MCore schedule。持续采集分三处接入，**尚未集成到 Relax**：

| 位置                       | 方案与约束                                                                                           |
| -------------------------- | ---------------------------------------------------------------------------------------------------- |
| MCore schedule             | 分开记录 forward/backward，附 step/PP 上下文；适用 actor 与 critic 两类角色；外包 `train_one_step` 无法拆开 `forward_backward_func` |
| Relax optimizer / 通信挂点 | optimizer 在调用边界计时；通信先用 trace 核实 stream 和完成边界                                      |
| rank 本地采集              | 训练线程只从预分配池取 Event、`record()`、把句柄放入有界 SPSC 队列                                   |
| 后台 → Straggler collector | 查询已完成 Event，经有界批量 HTTP 发送；不使用训练 process group                                     |
| collector → MetricsService | 拼接等价 peers、判定异常，只有聚合结果进入现有指标通路                                               |

默认关闭；开启后仅采样步记录 Event，不 `synchronize`，不新增训练 collective。现有 `MetricsServiceAdapter.log/flush` 会同步发 HTTP，不能由训练线程调用；每个 rank 的后台 sender 使用独立连接和超时，队列满、collector 不可达或返回非法响应时丢观测并计数，绝不反压训练。

collector 是独立 CPU-only 服务，不加入 NCCL/Gloo 组。它接收的最小 envelope 为：

```text
schema_version, run_id, topology_epoch, global_step, sample_seq,
global_rank, node_id, local_device,
tp_rank, pp_rank, vpp_rank, cp_rank, ep_rank, etp_rank, dp_rank, edp_rank,
stage_schema, workload{tokens,sequences,microbatches}, stages_ms{}, recorded_at
```

`(run_id, topology_epoch, global_rank, sample_seq)` 是幂等键；重复包忽略，旧 topology 数据不与新成员集合拼窗。窗口按 optimizer step 对齐，不用 rollout 步。collector 按 cohort 的 expected member set 与 TTL 关闭窗口：成员缺失、迟到或 stage schema 不一致都输出 `uncertain` 和 coverage，不把缺报补零。内存按 cohort 数、待完成窗口数和历史条数三重限界；淘汰必须产生 drop reason。

demo 验证过的机制与接入时才落地的设计分开：双卡 demo 已实现 Event 池取用、有界队列、按 (case, step, rank) 去重、乱序/缺报/schema 冲突的 `uncertain` 输出与按成员收齐关窗（传输为进程内队列，非 HTTP）；独立 CPU-only 服务、服务发现、run_id/topology_epoch 的生成与传播、批量 HTTP、发送超时、collector 重启恢复与时钟 TTL 属于接入时的设计承诺，尚无实现。后台 sender 的 GIL、Event query 与 HTTP 序列化成本没有隔离测量，demo 测得的只是含采集在内的整体配对开销。

报文预算：早期 demo 的简化 JSON payload 约 248 bytes/report，未包含上文拟议的完整 envelope，也不包含 HTTP 头和批量封装。作业级速率 = 完整报文实测字节数 × 每 rank 采样频率 × rank 数；若仍按 248 B 估算，1024 rank、每 8 步采样、约 1 step/s 时约 32 KB/s。这只是简化报文的参考量级，不能作为正式传输预算或上限。collector 的 CPU/内存与平台指标基数按 8/64/256/1024 rank 四档在接入后实测补齐，此处不预填。聚合结果送平台，逐 rank 样本仍可回查，保存范围与保留时长随首期 recipe 确定；告警可跳转到关联样本。

cohort 不是全 world。比较对象必须处于相同 TP/PP/VPP/CP/EP/ETP 位置，只在对应 DP/EDP replica 轴上不同；整步 forward/backward 还要求 token、sequence 与 microbatch 数在容差内。cohort 至少 2 个成员：目标 rank 之外至少 1 个对照；没有等价对照就只保存画像，不产生慢卡结论。双卡 demo 每个目标只有 1 个对照，刚满足这一下限。首期文本场景无 MoE；dense 与 expert 阶段的对照组规则（EP 轴如何参与等价判定）留待 MoE 挂点验收时确定，不提前承诺。

![TP2、PP2、DP2 示例：只比较同一分片位置的 DP 副本](https://raw.githubusercontent.com/shanyulu/Relax/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task11_straggler/results/cohort-map.svg)

阶段语义在 schema 中固定：

- `forward/backward` 记录 MCore schedule 内实际执行的本 rank 累计区间；PP/VPP 首期不重建全局 bubble，也不宣称是单 microbatch timeline。stages 是跨 chunk 累计口径：VPP>1 时无法定位单个 chunk，`vpp_rank` 仅作 schema 占位，首期不在该维度下结论；
- `optimizer` 只包 Relax 的 `optimizer.step()`，不把 scheduler、日志或下一步数据准备混入；
- `collective_interval` 只在已验证的 collective 边界上报。启用 overlap 时，外层墙钟区间不能代表 NCCL GPU 时间；没有可靠完成边界就报告 unavailable，而不是伪造 0；
- attention/MoE 只保留关闭状态的 schema capability，未完成真实挂点和开销验收前不算 v1 交付。

告警只比较同 cohort、同阶段、工作量可比的 rank；缺报、乱序和不可比样本打断连续异常判断。对端计算慢也会拉长本卡通信等待，因此报告异常区间，不直接归因网络。组内 `no alert` 也不能排除所有卡同时变慢。CUDA Event 区间度量 GPU stream 段，不含 CPU 发射停顿，两者在画像中并列展示、各自标注口径；采样步之间的短暂异常可能整体漏采，“无告警”只说明已采样窗口未满足判定条件，不等于无故障。根因输出在通信边界核实前一律标注为假设。

observer 的异常边界也需要明确：初始化、Event 分配、`record/query/elapsed_time`、序列化和发送中的异常都只禁用 observer 并留下计数，不从观测代码主动抛穿训练；如果 CUDA context 本身已经损坏，训练随后自行失败，不能把它包装成“观测降级成功”。关闭时有固定 deadline，未完成 Event 作废且不回池，后台线程不得阻止 actor 退出。

<details>
<summary>采集流程与告警规则</summary>

![采样步记录 Event，后台查询完成后回收](https://raw.githubusercontent.com/shanyulu/Relax/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task11_straggler/results/async-sampling.jpg)

![先核对等价副本和工作量，再判断持续异常](https://raw.githubusercontent.com/shanyulu/Relax/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task11_straggler/results/diagnosis.jpg)

</details>

## 取舍

与 [#363](https://github.com/redai-studio/Relax/pull/363) 在训练进程内用周期性 Gloo all-gather 汇总、由 primary 判定的做法相比，独立 CPU collector 多一跳传输和一个服务的运维。按其当前 diff（head `91b58bef`）核对，这笔代价买到两点它没有的性质：其一，它的判定与上报在 primary 训练线程内同步执行（reporter 经 `immediate=True` 同步发 HTTP），它自记的 late_arrival 案例正源于同类同步上报路径；把采集、判定、上报全部移出训练进程，正是本方案的第一动机；其二，它的窗口聚合是逐段累计和（每 rank 18 个 float64），无法还原 per-step 分布，间歇性变慢会被均值稀释，本方案保留逐采样步原始记录，p50/p95/max 随时可算。此外逐 rank 样本在聚合结果之外仍可回看，观测上报与训练指标通路解耦。这条取舍的传输与 CPU 成本尚未实测，接入后按上文四档预算补齐；若实测表明独立服务不划算，收敛回进程内汇总也是可接受的结果。

| 现有方案                                                                                                                     | 采用                             | 不直接采用                                                               |
| ---------------------------------------------------------------------------------------------------------------------------- | -------------------------------- | ------------------------------------------------------------------------ |
| [Megatron Core StragglerDetector](https://docs.nvidia.com/megatron-core/developer-guide/0.18.1/apidocs/core/core.utils.html) | CUDA Event、默认关闭、粗粒度区间 | 它的既有汇总与控制面不足以表达 Relax 的 rank × stage × workload 持久画像 |
| [NVIDIA Resiliency Extension](https://nvidia.github.io/nvidia-resiliency-ext/)                                               | 相对 peer、采样间隔、只观测模式  | v1 不终止训练，不把外部依赖作为必需项                                    |
| [OSDI 2025 what-if 研究](https://www.usenix.org/system/files/osdi25-lin-jinkun.pdf)                                          | 五个月集群 trace 的结论：straggler 多因、非平凡硬件故障，支持保留上下文与 `undetermined` 输出 | 其反事实模拟是离线根因分析，依赖集群级 trace 与模拟器；首期做训练内实时观测，不建模拟器 |
| [PyTorch Profiler](https://docs.pytorch.org/docs/stable/profiler.html) / `TrainProfiler`                                     | 用短 trace 校验挂点和 overlap    | 不常开 per-op trace，不把大文件作为持续上报格式                          |

## Demo 与未验证项

下图由双卡 demo 的逐样本数据生成，不是平台效果稿。

![实际 rank × 阶段结果视图](https://raw.githubusercontent.com/shanyulu/Relax/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task11_straggler/results/2gpu-v4-rank-view.png)

| 已验证                                                                                                                                                                                                                                                                                                                             | 结果与限制                                                                                                       |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| [v4 双卡实验](https://github.com/shanyulu/Relax/tree/7718e036c7144b68a01a8b608a4b463eb8e16ddd/demos/task11_straggler)                                                                                                                                                                                                              | 两轮开销中位数 0.116% / 0.146%；off/off 对照仍有系统偏移，不能据此认定 \<0.5%                                    |
| 采集与诊断                                                                                                                                                                                                                                                                                                                         | 两轮各接收 8064/8064 样本；最终 loss、参数一致；约 1.8× 前向变慢均在 step 16 定位 rank 1                         |
| [当前版本](https://github.com/shanyulu/Relax/tree/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task11_straggler)                                                                                                                                                                                                                 | 19 项测试通过；2026-09-24 用当前源码重跑生命周期 smoke，单对开销 0.321%，144/144 样本接收；单对仍不能证明 \<0.5% |
| [多会话机制实验](https://github.com/shanyulu/Relax/tree/8214cd7426885e94c931c91b2483086e310558ea/demos/task11_straggler/results/multisession-20260924)                                                                                                                                                                           | 4 个全新进程会话、16 对配对（3 会话在 GPU 0,1、1 会话在 GPU 2,3）：会话中位数 0.0017–0.2536%、合并 0.0861%，全部远低于 0.5%；但会话间漂移与效应同量级（A–D 差 0.178pp），跨 GPU 对 0.05pp 容差不成立，off/off 符号会话间翻转；单会话数字不足为凭，验收门槛坚持 ≥3 会话与 A/A |
| [恢复场景交互回放（下载后打开）](https://github.com/shanyulu/Relax/blob/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task11_straggler/results/2gpu-recovery-demo.html) · [预览图](https://github.com/shanyulu/Relax/blob/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task11_straggler/results/2gpu-recovery-demo-preview.jpg) | 224/224 样本接收；rank 1 只在中段变慢，随后回到 peer 范围；丢一条报告的按钮是接收端反事实回放                    |

![双卡机制实验：配对开销、off/off 基线波动、计算注入与采集质量](https://raw.githubusercontent.com/shanyulu/Relax/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task11_straggler/results/2gpu-v4-comparison.png)

两轮的开销中位数低于 0.5%，但 off/off 对照在第二轮出现 −0.211% 偏移，幅度超过该轮的开销中位数。图中的低开销不能推出真实 Relax recipe 的验收结论。

![Task 11 交互回放预览：异常、恢复与 rank × 阶段轨迹](https://raw.githubusercontent.com/shanyulu/Relax/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task11_straggler/results/2gpu-recovery-demo-preview.jpg)

**尚未完成官方验收。** 真实 recipe、collector/MetricsService 和通算 overlap 均未验证。当前 demo 的初始化和 Event.record 异常仍会抛出；上文描述的是 production 接入要满足的故障隔离契约，不是现有 demo 已具备的行为。

<details>
<summary>实验图、复现方法与完整记录</summary>

v4 每轮含 4 组 8000-step off/on 与 4 组 off/off，每次约 10.3–10.4 秒，每 8 步采样。置信区间、对照偏移、多会话记录、版本对应关系和历史试次见[证据记录](https://github.com/shanyulu/Relax/blob/8214cd7426885e94c931c91b2483086e310558ea/demos/task11_straggler/EVIDENCE.md)。v4 性能数据不代表后续修订版本。

</details>

## 如何验收

| 官方要求                     | 检查方法                                                                                                                                                                     |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 整体开销 \<0.5%（官方门槛） | 固定 recipe、工作量、采样和上报配置，交错 AB/BA、off/off 与 A/A 三种对照；计入后台、网络和 collector 成本；启动段与稳态段分开报告；估计对象为配对开销中位数，bootstrap 95% 上界同样 \<0.5%。窗口内多个 step 存在自相关，不当作独立样本；3 个新进程会话与观测覆盖率 ≥99% 是我方验收门槛（严于官方），为的是覆盖 off/off 观察到的运行间漂移 |
| 精度、loss、overlap 不受影响 | 对照 loss、参数和训练进度；短时 trace 检查已有通算 overlap，容差事先约定                                                                                                     |
| 实时上报、便于定位           | 展示 rank/阶段/cohort、覆盖率、drop reason 和从采样到平台可见的延迟；注入覆盖无注入对照、轻微与明显计算变慢、短暂与持续异常、恢复、工作量不均、host stall、通信等待与缺报乱序，报告检出率、误报、检测/恢复延迟和 `undetermined` 占比 |
| 观测失败不伤训练             | 注入 Event 池耗尽、队列满、collector 超时/重启、乱序/重复包和退出时未完成 Event；训练 step、loss 与 checkpoint 继续推进                                                      |

判定规则首期固定为：同 cohort、同 stage set、工作量差 ≤5%，且连续两个采样窗口满足 `observed / peer ≥ ratio` 与 `observed − peer ≥ absolute_ms`；缺报、乱序、stage 不一致均进入 `uncertain`，不进入持续异常计数。默认值只用于 demo，接入时由 recipe 校准。

实现顺序：用短 trace 核定 MCore 挂点和 overlap 语义；接通 rank 到 collector 的数据面；再接 MetricsService，跑完整 recipe 对照。采样率和覆盖率一起报告。请导师确认**首期 recipe、PP 配置，以及独立 CPU-only collector 的接入方式**。

参考：[官方 Task 11](https://github.com/redai-studio/community/blob/main/contributor-program/2026-cohort-2/official-task.md) · [导师背景补充](https://github.com/redai-studio/Relax/issues/334#issuecomment-5757682517) · [OSDI 2025 Straggler what-if 研究](https://www.usenix.org/system/files/osdi25-lin-jinkun.pdf) · [当前 main 的训练入口](https://github.com/redai-studio/Relax/blob/353ea7cec2c0d3f0745bc7929943089e51282e10/relax/backends/megatron/model.py#L1191)
