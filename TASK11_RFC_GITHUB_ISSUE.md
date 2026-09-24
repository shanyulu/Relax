# 【No.11】Relax Straggler 分析能力建设 - RFC

提案人：@shanyulu · 导师：@Lemon-412 · 状态：待评审

持续记录训练中每个 rank 的阶段耗时，定位持续变慢的区间，并保留工作量、并行位置和缺报信息。输出应回答“哪组可比 rank、哪个阶段出现异常”，不能把通信等待直接归因为坏卡或网络故障。

**截至 2026-09-24：已有双卡 standalone 机制实验，尚未接入真实 Relax 训练，未证明官方要求的整体开销 <0.5%。** 本文区分已测机制与待实现设计；只观测，不踢卡、不改变训练调度，范围遵循[导师公开答复](https://github.com/redai-studio/Relax/issues/334#issuecomment-5757676464)。

## 官方要求与首期交付

| 要求 | 首期方案 | 当前状态 |
| --- | --- | --- |
| 训练阶段耗时与 straggler 定位 | forward、backward、optimizer，以及完成边界已验证的通信区间 | 双卡 demo 有采集与注入；真实挂点待接入 |
| 定位到 rank、阶段和并行上下文 | 等价 peer 对照，附工作量、覆盖率、缺报与上报延迟 | demo 已验证部分判定；复杂并行未验收 |
| 整体开销 <0.5%，不影响精度及通算 overlap | 默认关闭、采样、有界异步采集；真实 recipe 配对对照 | 未通过整体开销验收；overlap 未验证 |
| 实时上报到指标平台 | 独立 CPU collector 汇总后接 MetricsService | 服务、HTTP 数据面与平台接入尚未实现 |

首期做文本 dense 训练。PP/VPP 先报告 rank 本地累计区间，不重建全局 bubble；attention/MoE 不计入已交付能力，没有可靠通信完成边界的阶段标为 unavailable。

## 接入方案

先复用现有 timer 接口，再判断是否需要新增挂点。当前 `relax/backends/megatron/model.py` 在 optimizer 配置、评估和训练路径将 `config.timers` 置为 None；向该接口注入非阻塞 timer，可利用 Megatron 已有调用点。用短 trace 核实其 forward/backward 和 overlap 边界，确实无法表达的区间才考虑 schedule 插桩，不预先改写 Megatron 调度器。

现有 `Timer` 和 `TrainProfiler` 保留原用途。持续采集拟按下表接入，**不是当前 demo 已完成的 Relax 集成**：

| 位置 | 职责与约束 |
| --- | --- |
| rank 训练线程 | 仅在采样步从预分配池取 Event、record、提交句柄；不 synchronize、不发 HTTP、不新增训练 collective |
| rank 后台 reader/sender | 查询已完成 Event，回收句柄，经有界队列批量发送；不能反压训练 |
| CPU-only collector | 按等价 peer 和 optimizer step 拼窗、诊断，保存可回查样本；不加入训练 NCCL/Gloo 组 |
| MetricsService | 接收聚合结果、覆盖率和故障计数；告警关联原始样本 |

队列满、collector 超时或响应非法时丢弃观测并计数。Event 初始化、分配、record/query/elapsed_time、序列化及发送异常都应限制在 observer 内；关闭时设置 deadline，未完成 Event 不回池，后台线程不得阻止 actor 退出。CUDA context 已损坏导致训练本身失败，不算“观测降级成功”。

这仍是实现约束：当前 demo 的初始化和 Event.record 异常尚可能抛出。把 HTTP 移到后台也不意味着零成本，GIL、Event query、序列化和 CPU 竞争必须计入开销实验。

## 什么样的 rank 才能比较

cohort 不是整个 world。目标 rank 至少要有一个等价 peer：同 TP/PP/CP 等分片位置，只在对应数据并行副本轴上不同，且阶段定义、token/sequence/microbatch 工作量可比。没有对照就保存画像，不下慢卡结论。双卡 demo 每个目标只有一个对照，只满足最低条件。

![TP2、PP2、DP2 的对照关系：只比较相同分片位置的 DP 副本](https://raw.githubusercontent.com/shanyulu/Relax/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task11_straggler/results/cohort-map.svg)

| 阶段 | 计时含义与限制 |
| --- | --- |
| forward / backward | 本 rank 实际执行区间的累计值；VPP 多 chunk 累计不能定位单个 chunk，不据此作 chunk 级诊断 |
| optimizer | `optimizer.step()` 边界，不混入 scheduler、日志或下一步准备 |
| collective_interval | 仅上报完成边界验证过的区间；overlap 下外层墙钟不等于 NCCL GPU 时间 |
| attention / MoE | 后续能力；expert 阶段的等价 peer 规则和挂点需要单独验证 |

判定同时使用相对比值与绝对耗时差。demo 采用工作量差 ≤5%、连续两个有效采样窗口的规则；这些是待 recipe 校准的参数，不是官方阈值。缺报、乱序、schema 冲突或不可比样本标为 `uncertain`，打断连续异常计数，不补零。

CUDA Event 描述 GPU stream 区间，不能替代 CPU 发射停顿；通信区间变长也可能来自同伴计算慢。报告区间异常与候选原因，不直接输出硬件故障结论。组内共同变慢、采样间隙中的短异常可能无法发现；“无告警”只表示有效采样窗口未满足规则。

<details>
<summary>数据契约与 collector 边界</summary>

拟议最小 envelope：

```text
schema_version, run_id, topology_epoch, global_step, sample_seq,
global_rank, node_id, local_device,
tp_rank, pp_rank, vpp_rank, cp_rank, ep_rank, etp_rank, dp_rank, edp_rank,
stage_schema, workload{tokens,sequences,microbatches}, stages_ms{}, recorded_at
```

`(run_id, topology_epoch, global_rank, sample_seq)` 为幂等键。窗口按 optimizer step 对齐，按 expected member set 与 TTL 关闭；不同 topology 或 stage schema 不混窗，输出覆盖率和缺报原因。窗口数、历史条数和 cohort 数均需有界，淘汰留下原因。VPP/EP 等字段不代表对应诊断能力已经实现。

demo 已有 Event 池、有界队列、本地队列传输、按 `(case, step, rank)` 去重及部分缺报/乱序处理。独立服务、服务发现、完整身份传播、批量 HTTP、发送超时、collector 重启和时钟 TTL 尚待接入。

早期简化报文约 248 B/report，不含完整 envelope、HTTP 头和批量封装，不能作正式预算。接入后实测“完整字节数 × 每 rank 采样频率 × rank 数”，以及 collector CPU、内存、积压和指标基数；原始样本保留时长随 recipe 明确。

</details>

## 已有实验能说明什么

下图来自双卡 demo 的逐样本数据，不是平台效果稿，也不是 Relax recipe 验收结果。

![双卡 demo 实测 rank × 阶段画像](https://raw.githubusercontent.com/shanyulu/Relax/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task11_straggler/results/2gpu-v4-rank-view.png)

| 实验版本 | 结果 | 能支持的结论 |
| --- | --- | --- |
| [v4 双卡实验](https://github.com/shanyulu/Relax/tree/7718e036c7144b68a01a8b608a4b463eb8e16ddd/demos/task11_straggler) | 两轮配对开销中位数 0.116% / 0.146%；各收齐 8,064 个样本，最终 loss/参数一致；约 1.8× forward 注入均在 step 16 定位 rank 1 | 采集与明显异常定位机制可行；off/off 存在偏移，不能据中位数判定 <0.5% |
| [第一批多会话](https://github.com/shanyulu/Relax/tree/8214cd7426885e94c931c91b2483086e310558ea/demos/task11_straggler/results/multisession-20260924) | 4 会话、16 对 off/on；合并中位数 +0.0861%；Session D 的 bootstrap **均值** 95% 区间上界 +0.8367% | D 未通过本提案的上界门槛；硬件对和运行顺序混杂，不能归因为某一 GPU 对 |
| [第二批多会话](https://github.com/shanyulu/Relax/tree/1e29727dd38e4b5086e01d7e97e6d31d47a29e7/demos/task11_straggler/results/multisession-20260924) | 4 会话、16 对 off/on，另有 16 对 A/A 和 16 对 off/off；off/on 中位数 +0.1844%，bootstrap **均值** 95% 区间上界 +0.7061% | 仍不能证明整体开销 <0.5%；A/A 不混入 off/on 开销样本池 |
| 同批 A/A（两臂均开 observer） | 配对中位数 +0.0135%；bootstrap **均值** 95% 区间 [−0.3332%, +0.1728%] | 描述 observer-on 重复运行的差异；区间包含零，不能证明无偏，也不能识别两臂共有的 observer 开销 |

这里的中位数与均值区间是不同统计量，保留标签是为如实记录历史结果，不能把均值 CI 当作中位数 CI。后续验收将预先统一估计量与区间方法，不重贴历史标签。

第一批干净负载段的持续告警计数为 A/B/C/D：2/1/2/0；尚未按有效 cohort-window 提供分母，不能写成误报率。第二批每会话收到 24,160/24,160 个样本，记录中无丢弃、loss 差异或参数错配；这些仍只是该 standalone 工作负载的结果。

**撤回旧版“CI 过零，因此观测器无偏”的结论。** A/A 不能支持这一推断，也不能据此断言环境漂移主导全部测量散布。森林图已按该口径重制——A/A 注记改为“与零一致、共同模式开销未识别”，off/off 只描述为“远超 A/A 散布”：

![多会话森林图（重制）：(a) off/on 配对开销两批次各自合并；(b) A/A 与零一致（共同模式开销未识别），off/off 漂移远超 A/A 散布](https://raw.githubusercontent.com/shanyulu/Relax/a99d94ec42be814e278b8aa198846f0a139f7563/demos/task11_straggler/results/multisession-20260924/multisession-forest.png)

[机制源码与测试](https://github.com/shanyulu/Relax/tree/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task11_straggler)有 19 项 demo 测试；[恢复场景回放](https://github.com/shanyulu/Relax/blob/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task11_straggler/results/2gpu-recovery-demo.html)展示异常后恢复，其中“丢一条报告”是接收端反事实回放，不是生产网络故障注入。不同版本的性能数字不用于证明后续实现的开销。

## 与现有工作的取舍

[#363](https://github.com/redai-studio/Relax/pull/363) 已有真实 Relax/Megatron 接入。以 [f203bff 快照](https://github.com/redai-studio/Relax/commit/f203bff50addca9e3e6054714bd809a9db84d04b) 为比较基线，其周期性 Gloo 汇总、primary 判定减少了独立服务的运维成本。旧版正文关于额外 `immediate=True` 同步 HTTP reporter 的描述不适用于该快照，予以删除。

本提案选择独立 collector，并保留逐采样步记录，代价是多一条传输链路和一套服务生命周期。是否值得，取决于两个待验证问题：

- 上报超时、collector 重启和积压时，训练能否不受观测链路拖累？
- 对间歇、轻微异常，逐样本记录能否提供窗口聚合之外的定位信息，且总成本仍符合门槛？

这不是“已优于 #363”的结论。如果维护者选用其主线，采集故障隔离、逐样本诊断和验证集可作为增量贡献，不必维护第二套同功能链路。

参考设计包括 Megatron timer、短时 profiler 对齐检查，以及官方推荐的 [OSDI ’25 论文](https://www.usenix.org/system/files/osdi25-lin-jinkun.pdf)。不引入外部必需依赖，不用常开 per-op trace 替代持续观测。

## 验收与实现顺序

1. **最小真实路径。** trace 核定 timer 边界，接通 observer、detector、collector 和 MetricsService；默认关闭。用真实训练 smoke 验证采集、上报和退出，不把“模块可导入”算接入完成。
2. **冻结实验协议。** 运行前固定 recipe、并行布局、工作量、采样/上报配置、warmup、会话数、AB/BA 顺序、统计方法及停止规则。校准与验证数据分开，失败试次留档，不为追过门槛反复筛选运行。
3. **性能与精度。** 配对中位数使用对应的 session-aware 区间，不能套均值 CI；step 有自相关，不作为独立重复。另报完整运行墙钟/吞吐、启动与稳态、尾延迟，计入后台、网络和 collector 成本。对照 loss、参数与训练进度，以短 trace 检查 overlap。官方门槛是整体开销 <0.5%；至少 3 个新进程会话、上界 <0.5% 和观测覆盖率 ≥99% 是本提案的验证安排，不是官方附加要求。
4. **诊断质量。** 覆盖无注入、轻微/明显、短暂/持续异常、恢复、工作量不均、host stall、通信等待和缺报乱序。报告检出率、以有效 cohort-window 为分母的误报率、检测/恢复延迟、uncertain 占比；说明无等价 peer、共同变慢及漏采的限制。
5. **故障隔离。** 注入 Event 池耗尽、队列满、发送超时、collector 重启、重复/乱序包和退出时未完成 Event；确认 step、loss 与 checkpoint 继续推进。安全性和性能实验分开，均使用最终代码版本。

结果关联到代码 commit、环境、配置和原始数据；图注不得强于对应实验。真实路径可审且 smoke 通过后提交 Draft PR，性能与故障证据完整后再申请正式评审。

请导师确认：**首期 recipe 与并行布局，以及是否接受独立 CPU collector；若已有统一方案，优先确认可复用接口和增量贡献范围。**

参考：[官方 Task 11](https://github.com/redai-studio/community/blob/main/contributor-program/2026-cohort-2/official-task.md) · [导师背景补充](https://github.com/redai-studio/Relax/issues/334#issuecomment-5757682517)
