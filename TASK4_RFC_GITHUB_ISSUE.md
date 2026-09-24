# 【No.4】GenRM 支持弹性扩缩容 - RFC

提案人：@shanyulu · 导师：@RexFlux · 状态：待评审

目标是在训练持续打分时，让 GenRM 从 1 个副本扩到 2 个，再缩回 1 个。新副本健康后才接流量；旧副本完成已接收的请求后才释放 GPU。手动 API 和 Autoscaler 使用同一套生命周期。GenRM 加载的是冻结模型，扩容不做权重同步。

![GenRM 弹性扩缩容：控制、打分与资源归属](https://raw.githubusercontent.com/shanyulu/Relax/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task4_genrm/results/cover.jpg)

## 首期范围

| 首期选择                      | 原因与限制                                                               |
| ----------------------------- | ------------------------------------------------------------------------ |
| 仅常驻 decoupled GenRM        | 不跨训练阶段搬迁；启动时拒绝 defer、共享 GPU、运行期 onload/offload 组合 |
| 新增副本独占 PG               | 只申请空闲资源，便于回滚与回收；初始 PG 和 owner 不变                    |
| 单 Gateway、单模型 Autoscaler | 手动 API 可选模型；别名归一后按模型互斥                                  |

一个逻辑副本可含多个 TP/PP workers，只发布 head。正常打分不增加逐次 Manager RPC；已缩掉的副本不能被 recovery 拉回。本期不做 Manager 重启恢复、多 Gateway 一致性或多模型自动调度。

## API 契约

`num_replicas` 是目标绝对总数，不是增减数量。POST 另接收可选模型选择、`timeout_secs` 和 `idempotency_key`。请求体指纹覆盖模型选择、目标数量与 `timeout_secs`。带 key 的重试按指纹分派：指纹一致时返回原 operation，`NOOP` 响应同样记录在案，重试逐字重放首次结果（含决策时刻的 `current`），容量变化后不会执行新操作；指纹不一致返回 409。没有 key 的第二个在途请求也返回 409。key 记录保留到操作终态后的可配置重放窗口，超期按新请求处理。并发保护与丢失响应后的安全重试由此同时成立。

| 接口                                           | 用途                                          |
| ---------------------------------------------- | --------------------------------------------- |
| POST `/genrm/scale_out`                        | 扩到目标总数                                  |
| POST `/genrm/scale_in`                         | 缩到目标总数，仅 graceful                     |
| GET `/genrm/engines`                           | 发现副本与路由                                |
| GET `/genrm/scale_out/{request_id}`            | 扩容进度、实际数量与逐副本结果                |
| GET `/genrm/scale_in/{request_id}`             | 缩容进度、实际数量与逐副本结果                |
| POST `/genrm/scale_out/{request_id}/reconcile` | 重试未完成的候选清理，不重新扩容              |
| POST `/genrm/scale_in/{request_id}/reconcile`  | 继续排空或清理已摘流量的副本，不重新选 victim |

请求依次经过以下检查；未知 request ID 返回 404。

| 顺序     | 规则                                                                                                 |
| -------- | ---------------------------------------------------------------------------------------------------- |
| 校验     | 数量须为正整数；所有目标不得低于 `initial`，缩容不得低于初始值；类型错误 422，范围或模型选择错误 400 |
| 幂等重放 | 同 key、同指纹（模型/目标/timeout）返回原 operation 或逐字重放 NOOP；同 key、不同指纹返回 409          |
| 互斥     | 其余请求若同模型有在途操作或未处理完的生命周期异常，返回 409，包括无 key 的同目标重复请求            |
| 执行     | 扩容目标 ≤ current、缩容目标 ≥ current：`200 NOOP`；否则 `200 PENDING`，返回 request ID 后异步执行   |

`initial` 是固定保护下限。`current` 是服务容量口径、`ready` 是可路由口径，实际资源占用另行暴露，三者不互相替代：

| replica 状态                                   | current | ready | 占用 PG/workers | cleanup_required |
| ---------------------------------------------- | ------- | ----- | --------------- | ---------------- |
| 未发布候选（CREATING / HEALTH_CHECKING）       | −       | −     | 是              | 清理失败时是     |
| ACTIVE（已发布、admission 开）                 | ✓       | ✓     | 是              | −                |
| DRAINING / REMOVING（已摘流、admission 关）    | ✓       | −     | 是              | −                |
| FAILED：缩容 victim，PG 未确认释放             | ✓       | −     | 是              | ✓                |
| FAILED：未发布候选，PG 未确认释放              | −       | −     | 是              | ✓                |
| REMOVED（已确认释放）                          | −       | −     | 否              | −                |

扩容候选清理失败时不计入 `current`，但资源仍被占用：`cleanup_required` 与模型互斥会挡住新的扩缩，直到 reconcile 完成。终态后重提按实际差额执行。

请求状态与副本状态分开，沿用 Rollout 扩缩语义：

- operation：扩容 `PENDING → CREATING → HEALTH_CHECKING → READY → ACTIVE`，终态 `ACTIVE/PARTIAL/FAILED`。成功终态沿用 Rollout `ScaleOutStatus` 的 `ACTIVE`，Autoscaler 现有终态判定可直接复用；不提供 `CANCELLED`，未竟清理走 reconcile。缩容 `PENDING → DRAINING → REMOVING → COMPLETED/FAILED`，对齐 `ScaleInStatus`。终态必须带 `target/current/ready/created/removed/failed/cleanup_required`。
- replica：`CREATING → HEALTH_CHECKING → READY → ACTIVE → DRAINING → REMOVING → REMOVED`，另有 `FAILED`。GenRM 不出现 `WEIGHT_SYNCING`。

## 生命周期

|      | 正常路径                                                         | 失败处理                                                               |
| ---- | ---------------------------------------------------------------- | ---------------------------------------------------------------------- |
| 扩容 | 独占 PG → 创建全部 workers → 加载冻结模型 → 健康检查 → 发布 head | 保留已就绪副本，清理未发布候选；超时后的迟到初始化不能发布             |
| 缩容 | 关闭新请求入口 → 排空已接收请求 → 停止全部 workers → 释放新增 PG | 入口关闭或排空失败，不 kill、不释放 PG、不自动恢复路由，暂停该模型扩缩 |
| 回收 | PG 申请后立即登记清理句柄                                        | worker/PG 未清理完则保留句柄重试，阻止继续扩缩；确认回收前不报成功     |

新旧副本固定相同 revision、tokenizer、模板、精度和并行配置。缩容只选新增副本，最近创建的优先；初始保护不妨碍服务 shutdown。扩容多副本逐个创建、独立健康检查，首个失败即停止：已发布副本保留并计入 `current`，operation 为 `PARTIAL`（`created/failed` 计数见终态字段），一个都没发布成功则 `FAILED`。`PARTIAL` 表示本次操作部分成功，不表示系统仍有可用副本；可用性以 `ready` 为准。

Gateway 和 direct client 最终都只访问 Task 3 发布的受控 ingress，不发布裸 SGLang 端口。ingress 在转发前原子取得 request lease；scale-in 的线性化点是把 `accepting=true` 切成 `false`。该点之后的新请求返回带 `rejected_before_accept` 标记的 503，只有这类 503 允许客户端安全重试；不带标记的 503 出自转发或基础设施故障，不能据此假定请求未执行。之前取得 lease 的请求不被取消；只有响应完成、显式 abort 已确认，或后端返回明确终态后才能释放 lease；客户端断线而后端结果未知时，lease 仍未完成。

旧路由请求只有在**明确未被 ingress 接收**时才能有界重选；连接已建立、响应超时或结果未知时不自动重放。drain 完成要求 request leases 归零，并由 GenRM 后端的 drain 确认接口返回证明：入口 lease 计数为零，且按 victim 的 engine generation 过滤后已接收任务表为空；旧 generation 迟到完成的任务不参与该判定。Prometheus 的 running/queue 只用于观测和交叉检查，不能单独授权回收。

![缩容接收边界：先取得租约的请求完成，关闭后的请求被拒绝；双重排空确认后才释放 GPU](https://raw.githubusercontent.com/shanyulu/Relax/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task4_genrm/results/drain-fence.svg)

一次缩容按 newest-first **逐副本**执行：前一个副本确认释放后才处理下一个，避免同时摘除过多可用容量。若目标需要移除多个副本而中途失败，已释放副本不回滚，未选择副本保持 ACTIVE；operation 为 FAILED，返回实际容量和固定 victim 列表。失败副本保持不可路由并暂停该模型扩缩，只能通过对应 reconcile 接口继续，不能重新选 victim，也不能被 recovery 拉回。

reconcile 延续原 operation：不产生新 request ID，成功后原 operation 进入终态并保留此前的 `removed` 计数。清理重试由 Manager 负责并以指数退避执行，reconcile 接口用于显式触发同一逻辑，两者幂等；重试期间该模型扩缩保持暂停。资源持续保留是失败隔离手段，恢复路径只有两条：reconcile，以及服务 shutdown 时按清理句柄回收。

<details>
<summary>扩容与缩容流程图</summary>

![扩容流程：独占 PG、初始化、健康检查后发布；失败清理候选](https://raw.githubusercontent.com/shanyulu/Relax/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task4_genrm/results/scale-out.jpg)

![缩容流程：关入口、排空、停止 workers、释放 PG；超时保留资源](https://raw.githubusercontent.com/shanyulu/Relax/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task4_genrm/results/scale-in.jpg)

</details>

## Autoscaler 与监控

复用现有策略、持续窗口和 cooldown，配置 GenRM 独立阈值，容量下限不低于 initial。手动与自动扩缩共用模型锁；Autoscaler 等待请求终态，按实际结果记录 history。

| 采集                                            | 展示                                                |
| ----------------------------------------------- | --------------------------------------------------- |
| token/KV 使用率、排队数、running requests、TTFT | `/status`、`/conditions`、`/scale_history`、TUI     |
| 指标有效性、目标与实际容量                      | initial/current/ready、触发条件、暂停原因、实际结果 |

指标经公共 discovery 和受控只读入口采集。现有 `MetricsCollector` 在 HTTP 200 但单个 Prometheus series 缺失时会用 0 填充；Task 4 需要把它改成**逐字段 validity**，否则“未暴露 TTFT”会被误判为低延迟。每个字段携带 `present/observed_at/sample_count`，缺失、过期或 histogram 无样本均不参与条件判断。

首期门槛偏保守，但缺数据要按成因区分，不能让保守策略变成永久停摆：

| 指标状态                             | 判定       | 自动扩缩行为                               |
| ------------------------------------ | ---------- | ------------------------------------------ |
| 所启用字段全部有效                   | 有效       | 正常决策                                   |
| 整体零流量（queue/running 有效为 0） | 有效零负载 | 可触发缩容；TTFT 无样本不构成暂停         |
| 新副本观测窗内尚无请求样本           | 观测未满   | 不阻塞整体决策；观测窗满仍缺按缺失处理   |
| 字段缺失、过期或采集失败             | 无效       | 暂停并在 `/conditions` 显示字段与原因     |

各字段的聚合方式（均值或分位）、单位、采样窗和分母（`ready`）在配置中固定并随 `/conditions` 暴露。只有 discovery 完整、无生命周期异常、连续窗口满足覆盖要求时才决策；手动 API 与打分不受影响。Autoscaler 等待 operation 终态后按实际结果写 history。

## 可运行契约 demo

[交互回放（下载后打开）](https://github.com/shanyulu/Relax/blob/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task4_genrm/results/contract-demo.html) · [预览图](https://github.com/shanyulu/Relax/blob/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task4_genrm/results/contract-demo-preview.jpg) · [事件记录](https://github.com/shanyulu/Relax/blob/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task4_genrm/results/contract-demo.json) · [源码与测试](https://github.com/shanyulu/Relax/tree/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task4_genrm)

![Task 4 契约回放预览：路由、在途请求与资源归属](https://raw.githubusercontent.com/shanyulu/Relax/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task4_genrm/results/contract-demo-preview.jpg)

回放覆盖 `1→2→1`、在途 `409`、未知请求 `404`、健康检查失败、迟到 dispatch、后端未排空、PG 清理失败、retry/reconcile 与 keyed NOOP 重放。页面逐步展示路由资格、在途请求与 PG owner。它使用 mock 对象验证提案中的状态和返回值；真实接入、打分与 GPU 回收还要在 Relax 中验收。HTML 需下载后用浏览器打开。

## Task 3 依赖边界

复用 Task 3 [RFC #71](https://github.com/redai-studio/Relax/issues/71) 的逻辑副本、路由与资源清理。#71 已承诺：Manager 幂等操作（`activate/drain/deactivate/shutdown`）、候选创建到发布的原子拓扑（`topology_revision` 递增）、PG ownership 表和 head-only discovery。当前候选 [PR #347](https://github.com/redai-studio/Relax/pull/347)（head `7813d61`）与 [PR #356](https://github.com/redai-studio/Relax/pull/356)（head `375ed00`）均未合入；按 2026-09-24 快照核对：#347 的 `AdmissionGate.close()` 会取消已进入代理的在途请求；#356 有拓扑与 drain 生命周期，但没有逐请求 admission 记账。两者都不能直接证明“已接收请求完整返回后才回收”。

#71 没有承诺逐请求 admission lease 或 drain fence。下表前两行是 Task 4 接入需要、两套候选都未提供的能力，属于 Task 3 评选时要裁决的缺口，而不是既成规范：

| 能力                                                                  | #71 是否承诺 | Task 4 依赖它保证什么                                |
| --------------------------------------------------------------------- | ------------ | ---------------------------------------------------- |
| 对单个逻辑副本原子关闭 admission，且不取消已接收请求                  | 否           | 迟到 dispatch 被拒绝，已有打分继续完成               |
| drain fence：入口租约与后端任务均已终态的可查询证明                   | 否           | 不能只凭 HTTP 连接关闭或 Prometheus 瞬时为零回收 GPU |
| 清理一个逻辑副本的全部 workers，并返回资源释放结果                    | 部分（PG ownership 表） | PG 未确认释放前保留 owner 与清理句柄，不误报成功     |
| 原子拓扑发布（`topology_revision`）、迟到结果丢弃（engine generation）| 拓扑发布是；generation 否 | 旧快照与超时后的迟到初始化结果不能重新发布           |

不要求 `registry_epoch`：快照排序用 `topology_revision`，迟到初始化用 engine generation 区分，重启恢复不在本期范围。

## 接入路径

| 改动点                                         | 现状（main `353ea7ce`）                     | 拟新增                                                                    |
| ---------------------------------------------- | ------------------------------------------- | ------------------------------------------------------------------------- |
| `relax/components/genrm.py`                    | 只有 generate/health/metrics/onload/offload | `/genrm/scale_out`、`/genrm/scale_in`、`/genrm/engines` 与状态查询，复用 `ScaleOutStatus`/`ScaleInStatus` |
| `relax/utils/autoscaler/autoscaler_service.py` | 仅轮询单个 `rollout_service_url`            | 按服务配置目标与 GenRM 独立阈值；终态判定沿用现有集合                    |
| `relax/utils/autoscaler/metrics_collector.py`  | HTTP 200 但 series 缺失时按 0 填充          | 逐字段 validity（`present/observed_at/sample_count`）                     |
| Task 3 ingress（上游依赖）                     | 两候选 PR 均未合入                          | admission 关闭不取消已接收请求、drain fence                               |

表中前三项改动不依赖 Task 3 评选结果，可先实现并用契约 demo 与单测验证；ingress 的排空与路由语义等 Task 3 定稿后接入。CPU demo 只覆盖契约模型，真实 Ray/SGLang 排空、PG 释放与 Autoscaler 决策要到文本 recipe 验收中取证。

## 如何验收

| 要求         | 检查方法                                                                                                        |
| ------------ | --------------------------------------------------------------------------------------------------------------- |
| API 与保护   | 绝对目标、终态后重复 NOOP、在途 409、非法 4xx；初始副本不删除，已缩副本不复活                                   |
| 手动扩缩     | 持续打分下 1→2→1；健康后实际接流量，新旧评分一致，全程无权重同步                                                |
| 排空与回滚   | 注入迟到 dispatch、客户端断线但后端仍忙、初始化失败、排空超时、worker/PG 清理失败；验证 reconcile 固定原 victim |
| 自动扩缩     | 高低负载至少三轮，覆盖空闲窗口、新副本无样本与采集失败场景；保存指标、决策日志、容量变化与 TUI 记录 |
| 文本训练 E2E | actor/rollout 持续推进，无新增打分失败或已接收请求丢失                                                          |

评分一致性测试固定输入和模型配置，使用确定性采样，提前约定容差。CPU 契约测试与 GPU 结果分开；多节点 TP/PP 未经真实验证不声明支持，不支持的弹性配置在启动时拒绝。

文本 recipe 验收计划：常驻 decoupled GenRM 从单机文本打分模型起步，固定输入集与确定性采样；持续打分下执行 1→2→1，留存操作日志（事件流与 demo 同构）、路由表前后对照（`/genrm/engines`）、每副本 GPU 与 PG 释放证据、Autoscaler 决策日志与指标窗口；新旧副本评分一致性按预定容差判定。

请导师确认 **Task 3 入选实现与「Task 3 依赖边界」一节需要裁决的两项缺口**（admission 关闭不取消已接收请求、drain fence）。首期限定常驻 decoupled、独占新增 PG、单 Gateway、单模型 Autoscaler。

参考：[官方 Task 4](https://github.com/redai-studio/community/blob/main/contributor-program/2026-cohort-2/official-task.md) · [Task 3 RFC](https://github.com/redai-studio/Relax/issues/71) · [当前 main 快照](https://github.com/redai-studio/Relax/tree/353ea7cec2c0d3f0745bc7929943089e51282e10)
