# 【No.4】GenRM 支持弹性扩缩容 - RFC

提案人：@shanyulu · 导师：@RexFlux · 状态：待评审

让 GenRM 在训练持续请求奖励时扩缩副本：新副本健康后接流量，缩容副本处理完已接收请求后释放 GPU。手动 API 与 Autoscaler 共用生命周期；模型冻结，不做权重同步。

**截至 2026-09-24：真实 Ray/SGLang 已跑通手动和自动 `1→2→1`，尚未完成官方验收。** 完整奖励一致性、训练连续性、故障路径和 TUI 仍需补齐。下面的契约是交付目标，不代表当前实现已全部满足。

## Task 3 接入边界

复用 [Task 3 RFC #71](https://github.com/redai-studio/Relax/issues/71) 的统一推理基础设施，不另建公开 ingress。Task 4 内部定义私有 `DrainTracker` 适配接口：关闭指定副本 admission，按 engine generation 等待已接收请求结束。

当前组件内计数只用于单 Gateway 验证。它不能证明 direct client、跨 Gateway 或客户端超时后仍在后端执行的请求已排空。**admission 关闭和后端排空证明由谁提供，需要与 Task 3 维护者确认；逐请求 lease/drain fence 不是 #71 已承诺的能力。**

首期限定常驻 decoupled GenRM、新增副本独占 PG、单 Gateway、单 GPU 逻辑副本。手动 API 可选模型；Autoscaler 只管理单模型 GenRM。运行期 onload/offload、共享 GPU、多节点 TP/PP、Manager 重启恢复和多 Gateway 一致性不在本期验收范围；不支持的弹性配置应在启动时拒绝。

## 官方要求与现有证据

GPU 实验使用 4×4090 服务器、Qwen3-0.6B 和单 Gateway 适配器，验证的是小模型生命周期，不替代正式训练 recipe 验收。

| 官方 Task 4 要求 | 已有证据 | 尚需完成 |
| --- | --- | --- |
| Manager 管理 PG、引擎启停与路由 | 手动 `1→2→1`；初始引擎存活，移除对象确为新增引擎 | PG ownership 失败出口、迟到初始化与清理失败注入 |
| 绝对目标、幂等、409/4xx、初始保护 | CPU 接口与生命周期回归 | 修复后的最终代码回归及故障路径复核 |
| 优雅排空、冻结模型、评分一致 | 持续生成时扩缩；三阶段短生成前缀一致 | 完整可解析奖励、逐请求引擎归属、后端排空证明 |
| GenRM 独立阈值与自动扩缩 | 一次自动 `1→2→1`，条件、历史和容量时间线留档 | 多轮与无效指标场景、动态容量指标、按 service 的 TUI |
| 训练不中断 | 生成负载没有请求失败 | 真实 recipe 中 actor、rollout、reward 同时持续推进 |

原始记录固定到产生该次证据的 commit：

| 实验 | 结果 | 证据边界 |
| --- | --- | --- |
| [手动扩缩](https://github.com/shanyulu/Relax/tree/a2ca6cb5b80fd20b372aa6e982805e345ce95dcd/demos/task4_genrm/results/e2e_run_20260924) | 扩容约 45 s、缩容约 1 s；4,163 个负载请求零失败；新增引擎服务 511 个请求 | `max_new_tokens=8`，只能证明短生成前缀一致，不能证明奖励评分一致 |
| [自动扩缩 v3](https://github.com/shanyulu/Relax/tree/105c69b59ae3896cfca7dd0e01bf5b606f00c0a7/demos/task4_genrm/results/autoscaler_run_20260924_v3) | 3,202 个请求零失败；新增引擎服务 516 个请求；最终容量回到初始值 | 一轮实验；使用实验阈值，不代表通用策略已校准 |
| 手动实验的资源记录 | Ray 空闲 GPU 为 `3→2→3`；新增 GPU 显存快照约 `4 MiB→21,792 MiB→4 MiB` | 正常路径回收证据；现有 verdict 尚未同时断言物理显存恢复与 PG `REMOVED` |

自动实验需要更正一处阶段解释：时间线首次观察到容量 2 约在 t=153.6 s，回到 1 约在 t=212.1 s；脚本约在 t=214.2 s 才切入 LOW′。因此缩容发生在 **STEADY 阶段**，不是 LOW′ 触发。决策记录是 `token_usage_low + no_queue + throughput_stable`；当时仍有在途请求。“低 KV 使用率”不等于“无流量”，该次运行也没有验证独立的空闲阶段。v3 将吞吐方差阈值从 0.1 调至 1.0；调参运行与冻结配置后的验收运行须分开。

下图由 v3 原始数据生成（绘制脚本与数据同目录），可视化上述阶段归属：上图为容量与决策/完成时刻——负载相位（阴影带）、`/scale_history` 决策时刻（虚线）与 operation 完成时刻（细实线）分别标出，缩容决策与完成均落在 STEADY 相位内；下图为初始/弹性引擎累计服务请求数。采样目标约 1 Hz（140 行覆盖约 149 s）；决策/完成时刻由 unix 时间戳经“完成时刻 ↔ 首次观测轮询”对齐（±1 s）映射到运行时钟。

![Autoscaler 全周期时间线：容量随负载自动 1→2→1；扩缩决策与完成时刻分别取自 /scale_history](https://raw.githubusercontent.com/shanyulu/Relax/71f855bcb9048b6af74d88b8c3437873a833f565/demos/task4_genrm/results/autoscaler_run_20260924_v3/timeline-chart.png)

## API 与容量口径

`num_replicas` 为目标绝对总数。请求可带模型选择、`timeout_secs`、`idempotency_key`；模型别名归一后按模型互斥。

| 接口 | 用途 |
| --- | --- |
| POST `/genrm/scale_out`、`/genrm/scale_in` | 扩到或缩到目标总数；缩容仅 graceful |
| GET `/genrm/engines` | 副本发现与路由 |
| GET `/genrm/scale_out/{request_id}`、`/genrm/scale_in/{request_id}` | 操作状态、实际容量和逐副本结果 |
| POST 上述状态路径的 `/reconcile` | 延续原操作的排空/清理，不新增副本、不重新选 victim |

处理顺序是校验、幂等重放、互斥检查、执行：

- 数量必须为正整数且不低于 `initial`；类型错误 422，范围或模型选择错误 400，未知 request ID 404。
- 同 key、同指纹返回原操作；指纹包含模型、目标和 timeout。同 key、不同指纹返回 409。`NOOP` 也保存并逐字重放首次结果，不能因后来容量变化而执行新操作。记录保留至终态后的可配置重放窗口，过期视为新请求。
- 除合法重放外，同模型有在途操作或未决清理时返回 409，包括无 key 的同目标请求。
- 扩容目标 ≤ current、缩容目标 ≥ current 返回 `200 NOOP`；否则返回 `200 PENDING` 和 request ID，异步执行。

`initial` 是固定保护下限；`current` 是已发布且尚未确认移除的容量，`ready` 是可路由容量。资源占用和未决清理另报，不能用 ready 代替实际占用。

| 副本状态 | current | ready | 占用 PG/workers | cleanup_required |
| --- | --- | --- | --- | --- |
| 未发布候选：CREATING / HEALTH_CHECKING | 不计入 | 不计入 | 已申请部分 | 清理失败时是 |
| ACTIVE，admission 开 | 计入 | 计入 | 是 | 否 |
| DRAINING / REMOVING，admission 关 | 计入 | 不计入 | 尚未确认全部释放 | 否 |
| FAILED：缩容 victim，PG 未确认释放 | 计入 | 不计入 | 未决 | 是 |
| FAILED：未发布候选，PG 未确认释放 | 不计入 | 不计入 | 未决 | 是 |
| REMOVED，已确认释放 | 不计入 | 不计入 | 否 | 否 |

扩容状态沿用 `ScaleOutStatus`：`PENDING → CREATING → HEALTH_CHECKING → READY → ACTIVE`，终态为 `ACTIVE/PARTIAL/FAILED`。缩容沿用 `ScaleInStatus`：`PENDING → DRAINING → REMOVING → COMPLETED/FAILED`。不引入 `RUNNING` 或 `WEIGHT_SYNCING`。

终态返回 `target/current/ready/created/removed/failed/cleanup_required`。`PARTIAL` 表示本次扩容已有部分副本发布、随后失败；可用性仍看 ready。FAILED/PARTIAL 不代表物理清理已经结束。

## 生命周期：发布、排空与回收

| 路径 | 必须满足的约束 |
| --- | --- |
| 创建 | PG 创建后立即登记 owner，再等待 readiness、创建 workers 和健康检查；所有失败出口都能找到清理句柄 |
| 发布 | 新旧副本固定模型 revision、tokenizer、模板、精度和并行配置；健康后才发布路由，超时后的迟到结果不得发布 |
| 缩容 | 仅选择新增副本，newest-first；逐个关闭 admission、排空、停止全部 workers、确认 PG 释放 |
| 失败 | 保留已发布的扩容成果；未发布候选清理失败不计容量，但保留资源账本和互斥。缩容失败 victim 不恢复路由、不重新选择 |
| recovery | 弹性副本永久退役后不得被通用 `recover()` 重建；正常服务 shutdown 仍能清理初始副本 |

操作超时只发 abort，不等于 Manager 物理线程已停止；`remove_placement_group()` 返回也不等于资源释放。原线程未结束时 reconcile 返回可重试冲突。只有物理执行结束、workers 清理完成且 PG 确认 `REMOVED`，才解除同模型互斥；未知状态继续保留 owner。

reconcile 使用原 request ID 和固定 victim，只推进遗留排空/清理，不补做扩容。原失败终态保留，清理结果和实际容量更新。多副本缩容中途失败时，已释放副本不回滚，未选择副本保持 ACTIVE。

下图是**拟议的接入契约，不是当前单 Gateway 计数已提供的保证**：

![拟议 drain fence：关闭接收后等待已接收任务终态，再回收资源](https://raw.githubusercontent.com/shanyulu/Relax/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task4_genrm/results/drain-fence.svg)

入口必须在转发前登记 accepted request；关闭 admission 后只对明确未接收的请求返回带 `rejected_before_accept` 的 503，允许有界重选。连接失败、普通 503、响应超时或结果未知均不自动重放。客户端断线不能直接结束后端记账。

排空证明须覆盖 victim 对应 generation 的入口记录和后端已接收任务；旧 generation 的迟到回调不能抵扣当前计数。Prometheus running/queue 只用于交叉检查，不能独自授权销毁。未接通这条链路前，不声称具备 direct client 或跨 Gateway 优雅排空。

## Autoscaler 与监控

保留单 deployment，Rollout 与 GenRM 分别拥有 engine discovery、collector、decision engine、debounce/cooldown、pending requests、history 和错误状态。`service_policies` 必须进入实际决策器，不能只存在配置中。手动与自动扩缩共用模型锁；终态仍有 cleanup_required 时暂停该模型决策。

每个指标携带有效性、观测时间和样本数；HTTP 200 不代表所有 series 都存在。每个条件使用自身需要的字段、覆盖率和分母，缺值不填 0。

| 观测情况 | 决策约束 |
| --- | --- |
| 所需字段有效、覆盖充分 | 正常判断 |
| 所有活跃引擎的 queue/running 有效为 0 | 可作为零负载证据；TTFT 没样本本身不否定空闲 |
| 新副本尚无样本 | 不把它当空闲；观测不足阻止缩容，不抹掉其他引擎有效的扩容证据 |
| 字段缺失、过期或采集失败 | 禁止依赖该字段的条件触发；缩容须取得全部活跃引擎的必要证据 |

按服务暴露 initial/current/ready、资源占用、未决清理、每引擎指标、条件、历史及禁止缩容原因，保留原 Rollout 字段和行为。

[实现快照 105c69b](https://github.com/shanyulu/Relax/tree/105c69b59ae3896cfca7dd0e01bf5b606f00c0a7) 已有服务隔离与自动扩缩链路，但不能据此声称监控交付完成：GenRM `/metrics` 的容量仍来自启动 spec；TUI 尚无 GenRM service 选择。PG owner 登记的失败窗口和 E2E 异常清理也需修复后重测。

| 接入位置 | 职责 |
| --- | --- |
| `relax/components/genrm.py` | API、操作注册表、幂等/互斥、发现与动态容量 |
| GenRMManager | PG ownership、workers 生命周期、发布/退役与 reconcile |
| `relax/utils/autoscaler/` | 服务运行上下文、字段有效性、策略、条件与历史 |
| monitor/TUI | 选择服务并展示该服务的数据；维持 Rollout 兼容 |
| 仓库 recipe / E2E driver | 真实训练与故障注入；外层 finally 覆盖全部异常出口，只回收本次资源 |

## 剩余验收

1. **生命周期安全。** 回归覆盖超时后互斥、迟到初始化、PG 各失败出口、固定 victim、退役不被 recover、三种容量口径；GPU 抽查长请求跨 drain、超时与 reconcile。资源验收同时断言 PG REMOVED 和物理 GPU 显存恢复。
2. **奖励一致性。** 固定完整输入集和模型配置，使用足够长的确定性生成，记录实际服务引擎并解析完整 judge 结果；容差在运行前写入 manifest。短前缀一致不计此项通过。
3. **自动扩缩。** 冻结阈值后至少三轮负载复测，覆盖真空闲、新副本无样本、指标缺失和带流量缩容；证明剩余容量能承接请求，保存 conditions、history、时间线与 TUI。三轮是本提案的复测安排，不是官方新增门槛。
4. **训练连续性。** 使用真实仓库 recipe/entrypoint，关联 actor 参数更新、rollout 产出、GenRM 请求完成与扩缩事件；报告停步时长、奖励延迟和样本返回率，排除 reward fallback 掩盖失败。不能以“脚本未报错”代替训练推进。

最终代码版本重跑后，每项结论关联要求、测试、配置、代码 commit、原始数据、结果与限制。CPU 契约、单 Gateway GPU 实验和正式训练验收分开列示。

<details>
<summary>契约 demo（mock，不作 GPU 或训练验收）</summary>

[源码与测试](https://github.com/shanyulu/Relax/tree/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task4_genrm) · [交互回放，下载后打开](https://github.com/shanyulu/Relax/blob/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task4_genrm/results/contract-demo.html) · [事件记录](https://github.com/shanyulu/Relax/blob/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task4_genrm/results/contract-demo.json)

覆盖幂等/NOOP、409/404、初始化失败、迟到 dispatch、排空与 PG 清理失败、retry/reconcile。它解释状态和接口行为，不证明真实 ingress 或后端排空。

</details>

请导师确认两项接入决定：**Task 3 的 admission/drain 适配责任；首期文本训练 recipe 与可接受的验收模型。**

参考：[官方 Task 4](https://github.com/redai-studio/community/blob/main/contributor-program/2026-cohort-2/official-task.md) · [Task 3 RFC #71](https://github.com/redai-studio/Relax/issues/71)
