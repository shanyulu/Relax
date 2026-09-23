# 【No.4】GenRM 支持弹性扩缩容 - RFC

提案人：@shanyulu · 导师：@RexFlux · 状态：待评审

为 GenRM 增加动态副本、Autoscaler 和 TUI。**健康后接流量，排空后释放资源，全程不做权重同步。** 本文是设计提案；下方 demo 只验证契约回放，真实 Relax 集成与 GPU 验收仍未完成。

![GenRM 弹性扩缩容：控制、打分与资源归属](https://raw.githubusercontent.com/shanyulu/Relax/codex/rfc-visuals/demos/task4_genrm/results/architecture.png)

## 先确定 Task 3 边界

复用 Task 3 [RFC #71](https://github.com/redai-studio/Relax/issues/71) 的逻辑副本、路由与资源清理。[#347](https://github.com/redai-studio/Relax/pull/347) 尚未合入，不把其接口当作已批准规范。集成前必须确认三项能力：**停止新请求但不取消在途请求、刷新路由、清理全部 workers**。

| 首期选择 | 原因与限制 |
| --- | --- |
| 仅常驻 decoupled GenRM | 不跨训练阶段搬迁；启动时拒绝 defer、共享 GPU、运行期 onload/offload 组合 |
| 新增副本独占 PG | 只申请空闲资源，便于回滚与回收；初始 PG 和 owner 不变 |
| 单 Gateway、单模型 Autoscaler | 手动 API 可选模型；别名归一后按模型互斥 |

一个逻辑副本可含多个 TP/PP workers，只发布 head。正常打分不增加逐次 Manager RPC；已缩掉的副本不能被 recovery 拉回。本期不做 Manager 重启恢复、多 Gateway 一致性或多模型自动调度。

## API 契约

`num_replicas` 是目标绝对总数，不是增减数量。POST 另接收可选模型选择与 `timeout_secs`。

| 接口 | 用途 |
| --- | --- |
| POST `/genrm/scale_out` | 扩到目标总数 |
| POST `/genrm/scale_in` | 缩到目标总数，仅 graceful |
| GET `/genrm/engines` | 发现副本与路由 |
| GET `/genrm/scale_out/{request_id}` | 扩容进度、实际数量与逐副本结果 |
| GET `/genrm/scale_in/{request_id}` | 缩容进度、实际数量与逐副本结果 |

请求依次经过以下检查；未知 request ID 返回 404。

| 顺序 | 规则 |
| --- | --- |
| 校验 | 数量须为正整数；所有目标不得低于 `initial`，缩容不得低于初始值；类型错误 422，范围或模型选择错误 400 |
| 互斥 | 同模型有在途操作或未处理完的生命周期异常，返回 409，包括同目标重复请求 |
| 执行 | 扩容目标 ≤ current、缩容目标 ≥ current：`200 NOOP`；否则 `200 PENDING`，返回 request ID 后异步执行 |

`initial` 是固定保护下限；`current` 包含排空中的副本，不含未发布候选和失败副本；`ready` 是可路由数。终态后重提按实际差额执行。

请求状态与副本状态分开，沿用 Rollout 扩缩语义：

- 扩容：`PENDING → CREATING → HEALTH_CHECKING → READY → ACTIVE`；部分成功为 `PARTIAL`，全失败为 `FAILED`，跳过 `WEIGHT_SYNCING`。
- 缩容：`PENDING → DRAINING → REMOVING → COMPLETED`；未全部移除为 `FAILED`，返回实际结果。

## 生命周期

| | 正常路径 | 失败处理 |
| --- | --- | --- |
| 扩容 | 独占 PG → 创建全部 workers → 加载冻结模型 → 健康检查 → 发布 head | 保留已就绪副本，清理未发布候选；超时后的迟到初始化不能发布 |
| 缩容 | 关闭新请求入口 → 排空已接收请求 → 停止全部 workers → 释放新增 PG | 入口关闭或排空失败，不 kill、不释放 PG、不自动恢复路由，暂停该模型扩缩 |
| 回收 | PG 申请后立即登记清理句柄 | worker/PG 未清理完则保留句柄重试，阻止继续扩缩；确认回收前不报成功 |

新旧副本固定相同 revision、tokenizer、模板、精度和并行配置。缩容只选新增副本，最近创建的优先；初始保护不妨碍服务 shutdown。

Gateway 和 direct client 共用 admission 检查。旧路由的迟到请求只有在**明确未接收**时才能有界重选；结果未知时不自动重放。已接收请求必须完成，后端也须确认排空；HTTP 完成或 metrics 为零不能单独作为回收依据。

<details>
<summary>扩容与缩容流程图</summary>

![扩容流程：独占 PG、初始化、健康检查后发布；失败清理候选](https://raw.githubusercontent.com/shanyulu/Relax/codex/rfc-visuals/demos/task4_genrm/results/scale-out.png)

![缩容流程：关入口、排空、停止 workers、释放 PG；超时保留资源](https://raw.githubusercontent.com/shanyulu/Relax/codex/rfc-visuals/demos/task4_genrm/results/scale-in.png)

</details>

## 可运行契约 demo

[交互回放（下载后打开）](https://github.com/shanyulu/Relax/blob/codex/rfc-visuals/demos/task4_genrm/results/contract-demo.html) · [预览图](https://github.com/shanyulu/Relax/blob/codex/rfc-visuals/demos/task4_genrm/results/contract-demo-preview.png) · [事件记录](https://github.com/shanyulu/Relax/blob/codex/rfc-visuals/demos/task4_genrm/results/contract-demo.json) · [源码与测试](https://github.com/shanyulu/Relax/tree/codex/rfc-visuals/demos/task4_genrm)

![Task 4 契约回放预览：路由、在途请求与资源归属](https://raw.githubusercontent.com/shanyulu/Relax/codex/rfc-visuals/demos/task4_genrm/results/contract-demo-preview.png)

模拟 `1→2→1`、在途 `409`、未知请求 `404`、健康检查失败、迟到 dispatch、后端未排空、PG 清理失败，以及显式 retry/reconcile。页面展示每一步的路由资格、在途请求和 PG owner；它是契约回放，不代表 Task 3 已集成或真实 GPU 验收。GitHub 的 `blob` 页面只显示源码，需下载 HTML 后在浏览器打开。

## Autoscaler 与监控

复用现有策略、持续窗口和 cooldown，配置 GenRM 独立阈值，容量下限不低于 initial。手动与自动扩缩共用模型锁；Autoscaler 等待请求终态，按实际结果记录 history。

| 采集 | 展示 |
| --- | --- |
| token/KV 使用率、排队数、running requests、TTFT | `/status`、`/conditions`、`/scale_history`、TUI |
| 指标有效性、目标与实际容量 | initial/current/ready、触发条件、暂停原因、实际结果 |

指标经公共 discovery 和受控只读入口采集。缺失、过期或无样本的 TTFT 不补零；缩容要求全部可路由副本的必要指标有效，扩容沿用覆盖率门槛。discovery 或生命周期异常时暂停决策，指标故障不阻断打分。

## 如何验收

| 要求 | 检查方法 |
| --- | --- |
| API 与保护 | 绝对目标、终态后重复 NOOP、在途 409、非法 4xx；初始副本不删除，已缩副本不复活 |
| 手动扩缩 | 持续打分下 1→2→1；健康后实际接流量，新旧评分一致，全程无权重同步 |
| 排空与回滚 | 注入迟到 dispatch、后端仍忙、初始化失败、排空超时、worker/PG 清理失败 |
| 自动扩缩 | 高低负载至少三轮，保存指标、决策日志、容量变化与 TUI 记录 |
| 文本训练 E2E | actor/rollout 持续推进，无新增打分失败或已接收请求丢失 |

评分一致性测试固定输入和模型配置，使用确定性采样，提前约定容差。CPU 契约测试与 GPU 结果分开；多节点 TP/PP 未经真实验证不声明支持，不支持的弹性配置在启动时拒绝。

请导师确认 **Task 3 集成基线及上述三项公共能力**，以及常驻 decoupled、独占新增 PG、单 Gateway、单模型 Autoscaler 的首期范围。先完成动态副本/API/排空，再接 Autoscaler/TUI，提交文本训练 E2E 与使用文档。

参考：[官方 Task 4](https://github.com/redai-studio/community/blob/main/contributor-program/2026-cohort-2/official-task.md) · [Task 3 RFC](https://github.com/redai-studio/Relax/issues/71) · [代码基线](https://github.com/redai-studio/Relax/tree/0651812093e3cd730302709b3db35ce0bb199e4b)
