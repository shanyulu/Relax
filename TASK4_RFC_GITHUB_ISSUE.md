# 【No.4】GenRM 支持弹性扩缩容 - RFC

提案人：@shanyulu · 导师：@RexFlux · 状态：待评审

目标是在训练持续打分时，让 GenRM 从 1 个副本扩到 2 个，再缩回 1 个。新副本健康后才接流量；旧副本完成已接收的请求后才释放 GPU。手动 API 和 Autoscaler 使用同一套生命周期。GenRM 加载的是冻结模型，扩容不做权重同步。

当前可公开复现的是契约 demo 和接口原型。生命周期原型的失败路径（物理完成栅栏、PG 释放确认、容量口径与 recovery 边界）已在本地分支实现并逐步用回归测试钉住，见「接入路径」末尾的验证状态表；真实 Ray/SGLang 排空、PG/GPU 回收、自动扩缩与训练不中断尚未完成 GPU 验收。下文描述拟交付行为，不代表现有代码已全部实现。

## 先确认 Task 3 接入边界

Task 4 复用 Task 3 的统一推理基础设施，不另建公开 ingress。内部只定义 `DrainTracker` 适配接口：关闭指定副本的新请求接收，按 generation 等待已接收请求归零，再允许销毁。组件内计数用于单 Gateway 测试，不能证明 direct client 或跨 Gateway 的请求已经排空。

需要与 Task 3 确认的是 admission 关闭与后端排空证明由谁提供。逐请求 lease 和按 generation 的排空证明是本提案的接入需求，不能当作 Task 3 已承诺或已实现的能力。生命周期、自动决策和单 Gateway 验证可以先推进。

![GenRM 弹性扩缩容：控制、打分与资源归属](https://raw.githubusercontent.com/shanyulu/Relax/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task4_genrm/results/cover.jpg)

## 首期范围

| 首期选择                      | 原因与限制                                                               |
| ----------------------------- | ------------------------------------------------------------------------ |
| 仅常驻 decoupled GenRM        | 不跨训练阶段搬迁；启动时拒绝 defer、共享 GPU、运行期 onload/offload 组合 |
| 新增副本独占 PG               | 只申请空闲资源，便于回滚与回收；初始 PG 和 owner 不变                    |
| 单 Gateway、单模型 Autoscaler | 手动 API 可选模型；别名归一后按模型互斥                                  |

首期从单 GPU 逻辑副本开始，多节点 TP/PP 留待后续验证。正常打分不增加逐次 Manager RPC；已缩掉的副本不能被 recovery 拉回。本期不做 Manager 重启恢复、多 Gateway 一致性或多模型自动调度。

| 官方 Task 4 要求 | 对应交付 |
| --- | --- |
| Manager 管理 PG、引擎启停和路由 | 健康后发布，停止 workers 并确认 PG 释放后完成缩容 |
| 手动 API、绝对目标、幂等和并发保护 | 同模型一项在途操作；未决清理也阻止下一次扩缩 |
| 优雅排空、保护初始副本 | 只移除新增副本，等待已接收请求结束 |
| 独立阈值和监控 | GenRM 独立决策状态，接入接口与 TUI |
| 评分一致、训练不中断 | 固定输入对照和真实文本训练 recipe 取证 |

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

拟议的最终接入路径是 Gateway 和 direct client 共用受控 ingress，具体由 Task 3 适配确认。入口在转发前记录已接收请求，scale-in 原子关闭新请求接收。关闭之后返回带 `rejected_before_accept` 标记的 503，只有这类响应允许安全重选；其他 503 不能证明请求未执行。已接收请求继续完成；响应结束、abort 已确认或后端返回明确终态后才结束记账。客户端断线而后端结果未知时，仍视为未完成。

旧路由请求只有在**明确未被 ingress 接收**时才能有界重选；连接已建立、响应超时或结果未知时不自动重放。drain 完成要求 request leases 归零，并由 GenRM 后端的 drain 确认接口返回证明：入口 lease 计数为零，且按 victim 的 engine generation 过滤后已接收任务表为空；旧 generation 迟到完成的任务不参与该判定。Prometheus 的 running/queue 只用于观测和交叉检查，不能单独授权回收。

![缩容接收边界：先取得租约的请求完成，关闭后的请求被拒绝；双重排空确认后才释放 GPU](https://raw.githubusercontent.com/shanyulu/Relax/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task4_genrm/results/drain-fence.svg)

一次缩容按 newest-first **逐副本**执行：前一个副本确认释放后才处理下一个，避免同时摘除过多可用容量。若目标需要移除多个副本而中途失败，已释放副本不回滚，未选择副本保持 ACTIVE；operation 为 FAILED，返回实际容量和固定 victim 列表。失败副本保持不可路由并暂停该模型扩缩，只能通过对应 reconcile 接口继续，不能重新选 victim，也不能被 recovery 拉回。

操作超时不等于物理线程停止，`remove_placement_group()` 返回也不等于资源释放。owner 和同模型互斥必须保留，直到物理执行结束、worker 清理完成且 Ray 确认 PG 为 `REMOVED`。查询失败或状态未知时继续阻止扩缩。

reconcile 延续原 operation，不产生新 request ID、不重新选择 victim、不补做扩容。保留原失败终态，更新实际容量与清理结果；只有确认清理完成才能解除互斥。服务 shutdown 也按保留的 ownership 清理资源。

<details>
<summary>扩容与缩容流程图</summary>

![扩容流程：独占 PG、初始化、健康检查后发布；失败清理候选](https://raw.githubusercontent.com/shanyulu/Relax/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task4_genrm/results/scale-out.jpg)

![缩容流程：关入口、排空、停止 workers、释放 PG；超时保留资源](https://raw.githubusercontent.com/shanyulu/Relax/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task4_genrm/results/scale-in.jpg)

</details>

## Autoscaler 与监控

保留单 deployment，为 Rollout 和 GenRM 分别保存 discovery、collector、策略、持续窗口、cooldown、pending requests、history 和错误状态。GenRM 的 `service_policies` 用于实际决策，容量下限不低于 initial。手动和自动扩缩共用模型锁；终态仍带 `cleanup_required` 时继续等待清理，history 记录实际结果。

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
| 字段缺失、过期或采集失败             | 无效       | 禁止依赖该字段的条件触发，在 `/conditions` 显示原因 |

每个条件使用自身必要字段的有效覆盖率与分母，并随 `/conditions` 展示单位、采样窗和禁止缩容原因。缩容需要所有活跃引擎的必要负载字段有效；扩容可使用覆盖率足够的正向证据，缺 TTFT 不应抹掉有效的高排队数。新增副本观测不足时不据此缩容。接口和 TUI 提供按服务视图，并保留原 Rollout 字段。

## 可运行契约 demo

[交互回放（下载后打开）](https://github.com/shanyulu/Relax/blob/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task4_genrm/results/contract-demo.html) · [预览图](https://github.com/shanyulu/Relax/blob/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task4_genrm/results/contract-demo-preview.jpg) · [事件记录](https://github.com/shanyulu/Relax/blob/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task4_genrm/results/contract-demo.json) · [源码与测试](https://github.com/shanyulu/Relax/tree/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task4_genrm)

![Task 4 契约回放预览：路由、在途请求与资源归属](https://raw.githubusercontent.com/shanyulu/Relax/1ed58a3d289df84afdb21b120656aa2a1114cda5/demos/task4_genrm/results/contract-demo-preview.jpg)

回放覆盖 `1→2→1`、在途 `409`、未知请求 `404`、健康检查失败、迟到 dispatch、后端未排空、PG 清理失败、retry/reconcile 与 keyed NOOP 重放。页面逐步展示路由资格、在途请求与 PG owner。它使用 mock 对象验证提案中的状态和返回值；真实接入、打分与 GPU 回收还要在 Relax 中验收。HTML 需下载后用浏览器打开。

## Task 3 依赖边界

复用 Task 3 [RFC #71](https://github.com/redai-studio/Relax/issues/71) 的逻辑副本、路由与资源清理。适配时需要逐项核对 Manager 幂等操作、原子拓扑发布、PG ownership 和 head-only discovery，并固定所采用的实现版本。

下表列出接入需求与 RFC 中的职责边界。逐请求 admission lease 和 drain fence 仍需与维护者确认：

| 能力                                                                  | #71 是否承诺 | Task 4 依赖它保证什么                                |
| --------------------------------------------------------------------- | ------------ | ---------------------------------------------------- |
| 对单个逻辑副本原子关闭 admission，且不取消已接收请求                  | 否           | 迟到 dispatch 被拒绝，已有打分继续完成               |
| drain fence：入口租约与后端任务均已终态的可查询证明                   | 否           | 不能只凭 HTTP 连接关闭或 Prometheus 瞬时为零回收 GPU |
| 清理一个逻辑副本的全部 workers，并返回资源释放结果                    | 部分（PG ownership 表） | PG 未确认释放前保留 owner 与清理句柄，不误报成功     |
| 原子拓扑发布（`topology_revision`）、迟到结果丢弃（engine generation）| 拓扑发布是；generation 否 | 旧快照与超时后的迟到初始化结果不能重新发布           |

不要求 `registry_epoch`：快照排序用 `topology_revision`，迟到初始化用 engine generation 区分，重启恢复不在本期范围。

## 接入路径

| 改动点                                         | main `353ea7ce` 现状                       | [接口原型 `601ee05`](https://github.com/shanyulu/Relax/tree/601ee05ce5873aa15d408dfeff2070771f1b567c) 与待完成工作 |
| ---------------------------------------------- | ------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `relax/components/genrm.py`                    | 只有 generate/health/metrics/onload/offload | `/genrm/scale_out`、`/scale_in`、`/engines` 与状态查询；状态机注册表复用 `ScaleOutStatus`/`ScaleInStatus`，含幂等（keyed NOOP 逐字重放）、互斥与绝对目标校验 |
| `relax/utils/autoscaler/config.py` + `autoscaler_service.py` | 仅轮询单个 `rollout_service_url` | 已有服务目标和策略配置；独立运行状态、实际决策与监控仍需接通验证 |
| `relax/utils/autoscaler/metrics_collector.py`  | HTTP 200 但 series 缺失时按 0 填充          | 逐字段 validity（`present/observed_at/sample_count`），并修复既有 N/A 格式化崩溃                        |
| GenRMManager 生命周期 / Task 3 ingress         | 均未实现                                    | 本地原型已实现失败清理、容量口径与 recovery 排除（验证状态见下表）；排空证明依赖 Task 3 ingress；真实 PG/GPU 回收尚未验收 |

生命周期原型的验证状态按证据强度分层，不以测试数量推导完成度：

| 状态 | 内容 | 依据 |
| --- | --- | --- |
| 已验证（回归 + mutation-check） | 终态推进等待物理完成：manager 汇报终态但物理执行未结束时，同模型新请求持续 409 | 把栅栏检查临时改回旧语义后回归必红、恢复后必绿 |
| 已验证（回归 + mutation-check） | 扩容失败候选在 PG 释放确认后从恢复路径退役；reconcile 延迟释放同样不再引用已删 PG | manager 级回归，bug 版 2 failed → 修复后通过 |
| 已验证（回归 + mutation-check） | Autoscaler 终态带未决清理时本地冻结该服务决策；各服务状态、策略与历史相互隔离 | 决策引擎与服务隔离测试 |
| 已验证（真实 Ray/SGLang GPU E2E，2026-09-24） | 持续打分下手动 1→2→1：扩容 `CREATING→HEALTH_CHECKING→ACTIVE`（45 s，弹性引擎落在独立探测的 PG/GPU 上）、缩容 `DRAINING→COMPLETED`（1 s）；初始引擎全程存活，恰好移除弹性引擎；弹性引擎实际服务 511 个请求；三个阶段的贪心打分逐字一致；全程 4,163 个负载请求零失败（扩容窗口 2,434 个、缩容窗口 52 个）；缩容后 GPU 显存与 Ray 空闲 GPU 归还基线 | 4×4090 + Qwen3-0.6B，`demos/task4_genrm/results/e2e_run_20260924`（E2E_PASS） |
| 已验证（真实 Ray/SGLang GPU E2E，2026-09-24） | **Autoscaler 全周期自动扩缩**：LOW 单引擎不误扩 → HIGH 持续饱和 60 s 内自动 1→2（`token_usage_high`，ACTIVE）→ STEADY 双引擎服务（弹性引擎 516 请求）→ 持续低载自动 2→1（`token_usage_low + no_queue + throughput_stable` 全条件，COMPLETED）→ 终态副本数 == 初始、初始引擎存活、3,202 请求零失败；决策与历史落 `/scale_history`，1 Hz 容量时间线留档。GenRM 使用独立于 Rollout 的服务目标与阈值 | 4×4090 + Qwen3-0.6B，`demos/task4_genrm/results/autoscaler_run_20260924_v3`（E2E_PASS，feat/task4-genrm-scale-api 分支） |
| 已实现、经逐行审查（暂无专门测试） | PG 删除后轮询 Ray 状态至 `REMOVED` 才视为释放；缩容 victim 未确认释放时保留容量计数、不继续选下一个、不报成功；`recover` 排除候选、排空中、退役与待清理 rank；GenRM 发现任意时刻聚合出多个有引擎的模型时跳过自动缩放，避免扩错目标 | 工作区 diff 审查记录；PG 释放路径已由上述 E2E 的缩容阶段实际走到（GPU/PG 归还基线） |
| 未验证（需真实资源） | 训练不中断（扩缩期间 actor/rollout 持续推进）——数据集（dapo-math-17k）已就位，为下一阶段工作 | — |

官方示例的 judge 为 Qwen3-VL-30B-A3B-Instruct × 8 GPU，本机 4×4090 无法承载；E2E 采用 Qwen3-0.6B 作为 GenRM judge 验证生命周期与路由正确性（官方要求的"新引擎打分与初始引擎一致"以贪心逐字一致证明），最终 recipe 级训练验收仍需导师确认可用的文本 GenRM 模型规模。

现有 CPU 测试检查接口契约、fake-manager 行为与上表已验证项；真实训练连续性仍需单独取证。实测过程暴露并修复了若干仅在真实 Ray/SGLang 下可见的问题（ray 2.5x 无 `wait_for_ready`、scale-out PG 需探测物理 GPU 而非本地索引、Serve 代理容器内仅绑 localhost、radix cache 使相同 prompt 的 KV 共享导致负载不饱和），修复均有独立 commit 与复现记录。

## 如何验收

| 要求         | 检查方法                                                                                                        |
| ------------ | --------------------------------------------------------------------------------------------------------------- |
| API 与保护   | 绝对目标、终态后重复 NOOP、在途 409、非法 4xx；初始副本不删除，已缩副本不复活                                   |
| 手动扩缩     | 持续打分下 1→2→1；健康后实际接流量，新旧评分一致，全程无权重同步                                                |
| 排空与回滚   | 注入迟到 dispatch、客户端断线但后端仍忙、初始化失败、排空超时、worker/PG 清理失败；验证 reconcile 固定原 victim |
| 自动扩缩     | 高低负载至少三轮，覆盖空闲窗口、新副本无样本与采集失败场景；保存指标、决策日志、容量变化与 TUI 记录 |
| 文本训练 E2E | actor/rollout 持续推进，无新增打分失败或已接收请求丢失                                                          |

评分一致性测试固定输入和模型配置，使用确定性采样，提前约定容差。CPU 契约测试与 GPU 结果分开；多节点 TP/PP 未经真实验证不声明支持，不支持的弹性配置在启动时拒绝。

执行顺序：失败路径回归先行（栅栏、清理残留与决策冻结已按验证状态表钉住，其余注入项随 GPU 阶段补齐），再做手动 GPU `1→2→1`、至少三轮自动高低负载，最后用真实仓库 recipe/entrypoint 验证训练持续推进。按稳定副本标识核对新增与移除对象，保存每副本打分、worker、PG/GPU 释放、条件与历史记录。脚本用 `try/finally` 清理本次拥有的资源。三轮负载是本提案的复测安排，官方要求是自动扩缩及训练不中断。

Task 3 公开 ingress 接通前，运行结果只标为单 Gateway 适配器证据，不宣称 direct client 或跨 Gateway 排空已验收。

请导师确认 **Task 3 入选实现与「Task 3 依赖边界」一节需要裁决的两项缺口**（admission 关闭不取消已接收请求、drain fence）。首期限定常驻 decoupled、独占新增 PG、单 Gateway、单模型 Autoscaler。

参考：[官方 Task 4](https://github.com/redai-studio/community/blob/main/contributor-program/2026-cohort-2/official-task.md) · [Task 3 RFC](https://github.com/redai-studio/Relax/issues/71) · [当前 main 快照](https://github.com/redai-studio/Relax/tree/353ea7cec2c0d3f0745bc7929943089e51282e10)
