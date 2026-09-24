# 【No.4】GenRM 支持弹性扩缩容 - RFC

提案人：@shanyulu · 导师：@RexFlux · 状态：待评审

目标是在训练持续打分时，让 GenRM 从 1 个副本扩到 2 个，再缩回 1 个。新副本健康后才接流量；旧副本完成已接收的请求后才释放 GPU。手动 API 和 Autoscaler 使用同一套生命周期。GenRM 加载的是冻结模型，扩容不做权重同步。

![GenRM 弹性扩缩容：控制、打分与资源归属](https://raw.githubusercontent.com/shanyulu/Relax/7159d9096a22024078cbbae6b75d0b5bd8510132/demos/task4_genrm/results/cover.jpg)

## 先确定 Task 3 边界

复用 Task 3 [RFC #71](https://github.com/redai-studio/Relax/issues/71) 的逻辑副本、路由与资源清理。当前有 [PR #347](https://github.com/redai-studio/Relax/pull/347) 与 [PR #356](https://github.com/redai-studio/Relax/pull/356) 两套候选实现，均未合入；Task 4 不把任一套私有接口写成既定规范。

截至 2026-09-24 的代码快照里，#347 有 per-engine admission ingress，但关闭入口会取消已进入代理的请求；#356 有拓扑状态与 drain 生命周期，但没有逐请求 admission 记账。两者都不能直接证明“已接收请求完整返回后才回收”。因此 Task 3 的选择不是普通适配问题，而是实现前置门槛：

| Task 3 必须提供的公共契约                                | Task 4 依赖它保证什么                                |
| -------------------------------------------------------- | ---------------------------------------------------- |
| 对单个逻辑副本原子关闭 admission；关闭不取消已接收请求   | 迟到 dispatch 被拒绝，已有打分继续完成               |
| 返回 drain fence：入口租约与后端任务均已终态             | 不能只凭 HTTP 连接关闭或 Prometheus 瞬时为零回收 GPU |
| 清理一个逻辑副本的全部 workers，并返回资源释放结果       | PG 未确认释放前保留 owner 与清理句柄，不误报成功     |
| `registry_epoch + topology_revision + engine generation` | 旧 Manager、旧快照和迟到初始化结果不能重新发布       |

| 首期选择                      | 原因与限制                                                               |
| ----------------------------- | ------------------------------------------------------------------------ |
| 仅常驻 decoupled GenRM        | 不跨训练阶段搬迁；启动时拒绝 defer、共享 GPU、运行期 onload/offload 组合 |
| 新增副本独占 PG               | 只申请空闲资源，便于回滚与回收；初始 PG 和 owner 不变                    |
| 单 Gateway、单模型 Autoscaler | 手动 API 可选模型；别名归一后按模型互斥                                  |

一个逻辑副本可含多个 TP/PP workers，只发布 head。正常打分不增加逐次 Manager RPC；已缩掉的副本不能被 recovery 拉回。本期不做 Manager 重启恢复、多 Gateway 一致性或多模型自动调度。

## API 契约

`num_replicas` 是目标绝对总数，不是增减数量。POST 另接收可选模型选择、`timeout_secs` 和 `idempotency_key`。请求体指纹覆盖模型选择、目标数量与 `timeout_secs`：同 key 同指纹的重试返回原 operation；`NOOP` 同样是被记录的决策，同 key 重试逐字重放首次响应（携带决策时刻的 `current`，容量变化后也不会执行新操作）；同 key 不同指纹返回 409。没有 key 的第二个在途请求仍返回 409。key 记录保留到对应操作终态后的可配置重放窗口，超期按新请求处理。这样既保留并发保护，也覆盖客户端丢失首个响应后的安全重试。

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

`initial` 是固定保护下限；`current` 包含 `ACTIVE/DRAINING/REMOVING`，不含未发布候选与已确认释放的副本；`ready` 只统计 admission 打开且可路由的副本。清理未决的 replica 仍计入 `current`，并令 `cleanup_required=true`。终态后重提按实际差额执行。

请求状态与副本状态分开，沿用 Rollout 扩缩语义：

- operation：扩容 `PENDING → CREATING → HEALTH_CHECKING → READY → ACTIVE`，终态 `ACTIVE/PARTIAL/FAILED`。成功终态沿用 Rollout `ScaleOutStatus` 的 `ACTIVE`，Autoscaler 现有终态判定可直接复用；不提供 `CANCELLED`，未竟清理走 reconcile。缩容 `PENDING → DRAINING → REMOVING → COMPLETED/FAILED`，对齐 `ScaleInStatus`。终态必须带 `target/current/ready/created/removed/failed/cleanup_required`。
- replica：`CREATING → HEALTH_CHECKING → READY → ACTIVE → DRAINING → REMOVING → REMOVED`，另有 `FAILED`。GenRM 不出现 `WEIGHT_SYNCING`。

## 生命周期

|      | 正常路径                                                         | 失败处理                                                               |
| ---- | ---------------------------------------------------------------- | ---------------------------------------------------------------------- |
| 扩容 | 独占 PG → 创建全部 workers → 加载冻结模型 → 健康检查 → 发布 head | 保留已就绪副本，清理未发布候选；超时后的迟到初始化不能发布             |
| 缩容 | 关闭新请求入口 → 排空已接收请求 → 停止全部 workers → 释放新增 PG | 入口关闭或排空失败，不 kill、不释放 PG、不自动恢复路由，暂停该模型扩缩 |
| 回收 | PG 申请后立即登记清理句柄                                        | worker/PG 未清理完则保留句柄重试，阻止继续扩缩；确认回收前不报成功     |

新旧副本固定相同 revision、tokenizer、模板、精度和并行配置。缩容只选新增副本，最近创建的优先；初始保护不妨碍服务 shutdown。

Gateway 和 direct client 最终都只访问 Task 3 发布的受控 ingress，不发布裸 SGLang 端口。ingress 在转发前原子取得 request lease；scale-in 的线性化点是把 `accepting=true` 切成 `false`。该点之后的新请求返回可重试的 503，之前取得 lease 的请求不被取消。只有响应完成、显式 abort 已确认，或后端返回明确终态后才能释放 lease；客户端断线而后端结果未知时，lease 仍未完成。

旧路由请求只有在**明确未被 ingress 接收**时才能有界重选；连接已建立、响应超时或结果未知时不自动重放。drain 完成要求 request leases 归零，并由后端确认没有已接收任务；Prometheus 的 running/queue 只用于观测和交叉检查，不能单独授权回收。

![缩容接收边界：先取得租约的请求完成，关闭后的请求被拒绝；双重排空确认后才释放 GPU](https://raw.githubusercontent.com/shanyulu/Relax/7159d9096a22024078cbbae6b75d0b5bd8510132/demos/task4_genrm/results/drain-fence.svg)

一次缩容按 newest-first **逐副本**执行：前一个副本确认释放后才处理下一个，避免同时摘除过多可用容量。若目标需要移除多个副本而中途失败，已释放副本不回滚，未选择副本保持 ACTIVE；operation 为 FAILED，返回实际容量和固定 victim 列表。失败副本保持不可路由并暂停该模型扩缩，只能通过对应 reconcile 接口继续，不能重新选 victim，也不能被 recovery 拉回。

<details>
<summary>扩容与缩容流程图</summary>

![扩容流程：独占 PG、初始化、健康检查后发布；失败清理候选](https://raw.githubusercontent.com/shanyulu/Relax/7159d9096a22024078cbbae6b75d0b5bd8510132/demos/task4_genrm/results/scale-out.jpg)

![缩容流程：关入口、排空、停止 workers、释放 PG；超时保留资源](https://raw.githubusercontent.com/shanyulu/Relax/7159d9096a22024078cbbae6b75d0b5bd8510132/demos/task4_genrm/results/scale-in.jpg)

</details>

## 可运行契约 demo

[交互回放（下载后打开）](https://github.com/shanyulu/Relax/blob/7159d9096a22024078cbbae6b75d0b5bd8510132/demos/task4_genrm/results/contract-demo.html) · [预览图](https://github.com/shanyulu/Relax/blob/7159d9096a22024078cbbae6b75d0b5bd8510132/demos/task4_genrm/results/contract-demo-preview.jpg) · [事件记录](https://github.com/shanyulu/Relax/blob/7159d9096a22024078cbbae6b75d0b5bd8510132/demos/task4_genrm/results/contract-demo.json) · [源码与测试](https://github.com/shanyulu/Relax/tree/7159d9096a22024078cbbae6b75d0b5bd8510132/demos/task4_genrm)

![Task 4 契约回放预览：路由、在途请求与资源归属](https://raw.githubusercontent.com/shanyulu/Relax/7159d9096a22024078cbbae6b75d0b5bd8510132/demos/task4_genrm/results/contract-demo-preview.jpg)

回放覆盖 `1→2→1`、在途 `409`、未知请求 `404`、健康检查失败、迟到 dispatch、后端未排空、PG 清理失败和 retry/reconcile。页面逐步展示路由资格、在途请求与 PG owner。它使用 mock 对象验证提案中的状态和返回值；真实接入、打分与 GPU 回收还要在 Relax 中验收。HTML 需下载后用浏览器打开。

## Autoscaler 与监控

复用现有策略、持续窗口和 cooldown，配置 GenRM 独立阈值，容量下限不低于 initial。手动与自动扩缩共用模型锁；Autoscaler 等待请求终态，按实际结果记录 history。

| 采集                                            | 展示                                                |
| ----------------------------------------------- | --------------------------------------------------- |
| token/KV 使用率、排队数、running requests、TTFT | `/status`、`/conditions`、`/scale_history`、TUI     |
| 指标有效性、目标与实际容量                      | initial/current/ready、触发条件、暂停原因、实际结果 |

指标经公共 discovery 和受控只读入口采集。现有 `MetricsCollector` 在 HTTP 200 但单个 Prometheus series 缺失时会用 0 填充；Task 4 必须把它改成**逐字段 validity**，否则“未暴露 TTFT”会被误判为低延迟。每个字段携带 `present/observed_at/sample_count`，缺失、过期或 histogram 无样本均不参与条件判断。

首期采用保守门槛：任一 ready 副本缺少所启用策略的必要字段，自动扩缩都暂停并在 `/conditions` 显示原因；手动 API 与打分不受影响。只有 discovery 完整、无生命周期异常、连续窗口满足覆盖要求时才决策。Autoscaler 使用 `ready` 做负载分母、`current` 做容量目标，等待 operation 终态后按实际结果写 history。

## 如何验收

| 要求         | 检查方法                                                                                                        |
| ------------ | --------------------------------------------------------------------------------------------------------------- |
| API 与保护   | 绝对目标、终态后重复 NOOP、在途 409、非法 4xx；初始副本不删除，已缩副本不复活                                   |
| 手动扩缩     | 持续打分下 1→2→1；健康后实际接流量，新旧评分一致，全程无权重同步                                                |
| 排空与回滚   | 注入迟到 dispatch、客户端断线但后端仍忙、初始化失败、排空超时、worker/PG 清理失败；验证 reconcile 固定原 victim |
| 自动扩缩     | 高低负载至少三轮，保存指标、决策日志、容量变化与 TUI 记录                                                       |
| 文本训练 E2E | actor/rollout 持续推进，无新增打分失败或已接收请求丢失                                                          |

评分一致性测试固定输入和模型配置，使用确定性采样，提前约定容差。CPU 契约测试与 GPU 结果分开；多节点 TP/PP 未经真实验证不声明支持，不支持的弹性配置在启动时拒绝。

请导师确认 **Task 3 入选实现和上表四项公共契约**。确定这层接口后，Task 4 先实现手动扩缩与排空，再接 Autoscaler、TUI 和文本训练验收。首期限定常驻 decoupled、独占新增 PG、单 Gateway、单模型 Autoscaler。

参考：[官方 Task 4](https://github.com/redai-studio/community/blob/main/contributor-program/2026-cohort-2/official-task.md) · [Task 3 RFC](https://github.com/redai-studio/Relax/issues/71) · [当前 main 快照](https://github.com/redai-studio/Relax/tree/353ea7cec2c0d3f0745bc7929943089e51282e10)
