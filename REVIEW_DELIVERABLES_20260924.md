# Task 4 / Task 11 技术审查交付（2026-09-24，实施状态已更新）

依据：官方任务规范（community/contributor-program/2026-cohort-2/official-task.md）、相关 Issue/PR 公开正文与评论（2026-09-24 经 gh api 取证）、upstream main `353ea7ce`、本地代码与 demo 实跑。所有修改均注明依据；未验证项单列，不包装为已确认。

> 实施复核：此前“全部修复”仅覆盖 RFC/契约层，不能代表真实生命周期和自动扩缩已验收。当前实现仍在本地 dirty worktree：已补显式 physical-completion fence、PG `REMOVED` 确认、失败缩容容量保留、recover 排除与 dirty-terminal reconcile；尚未完成真实 GenRM/训练 GPU E2E、Task 3 ingress lease 适配和公开发布。历史修复表保留为审查轨迹，不应被引用为最终验收结论。

---

## A. 按维度对比（事实 [来源] / 判断）

### Task 11（我们 #357 vs #334 vs #362）

| 维度 | #357（我们） | #334 | #362 |
|---|---|---|---|
| 真实 Relax 接入 | 无（正文自认）[357] | 无（standalone demo）[334] | 有：PR #363 draft，+2163/−5，head `91b58bef` [363] |
| 真实硬件实验 | 部分：双卡机制 demo [357] | 部分：2 卡 standalone [334] | 有：8×A100 Relax 自带 recipe（DP8）[362] |
| 开销数据 | 0.116%/0.146%（自认不能证明 <0.5%）[357+EVIDENCE 重算] | 0.479%（非 recipe）[334] | 交替开关 1 对 −0.05%±0.37%，CI 上界 +0.32%<0.5%（自认需补 A/A 与多对）[362] |
| 对照设计 | off/off 已跑，AB/BA 属计划 [357] | 仅开/关对比 [334] | in-run 交替+双相位；A/A 未跑 [362] |
| 故障注入 | 1.8× 计算变慢定位 + 恢复回放 [357] | 1.94× 检出 [334] | SM 2.52×（z=109、0 误报）+ 真实 late_arrival [362] |
| 导师互动 | 无（0 评论）[357] | 方向拍板 + 追问（**非入选**）[334 评论 5757676464 等] | 无（仅 bot 评审）[363] |
| 诚实标注缺口 | 有 [357] | 有（§9.3）[334] | 有（缺口清单）[362] |

**判断**：#362 在真实接入与硬件证据上领先，是当前基线；其开销证据仍只有 1 对交替实验。#334 的导师互动属方向反馈而非正式入选（看板规则为统一评审、每题一成果）。我们 #357 的差异化在诚实边界与对照/覆盖率设计；短板是无 Relax 集成与真实 recipe 数据。看板 #321 上 Mukayi 仍标"暂无 RFC"是滞后（看板更新 09-23 09:47Z 早于 #362 创建 17:06Z），不能据此断言。

### Task 4（我们 #351 vs 其他报名者）

- 看板 5/5 认领：Dayuxiaoshui / **shanyulu（#351 待评审）** / Saddss / ldemon2333 / leelingrui；除我们外**未见其他 No.4 RFC**（浏览 #335–#364 标题）[事实]。
- **判断**：不能宣布领先——他人可能未公开材料。竞争信号：#347 作者 ldemon2333 同时在修上游多节点 scale-out hang（issue #360 + PR #361），正深入相关基础设施。
- SigureMo 已人工介入两个 Task 3 PR（#347 批评全依赖 agent 判断、#356 CHANGES_REQUESTED），对 #351 零表态 [事实]。

---

## B. 问题清单及修复证据（按严重程度）

### Task 4（RFC #351）— RFC/契约问题已修订；真实实现与验证进行中

| # | 严重度 | 问题 | 修复 | 证据/commit |
|---|---|---|---|---|
| 1 | **高（契约矛盾）** | RFC 扩容终态写 `COMPLETED`，但 Rollout `ScaleOutStatus`（rollout.py:244-257）与 Autoscaler 终态集合（scaling_decision.py:24-25）均为 `ACTIVE`；`RUNNING` 不存在；按 RFC 实现会让 autoscaler_service.py:569 的 pending 请求永不终态、全模型自动扩缩永久阻塞 | RFC L70 改为扩容 `PENDING→CREATING→HEALTH_CHECKING→READY→ACTIVE`、缩容对齐 `ScaleInStatus` | `bc0311f`；官方要求"对齐 RolloutManager 扩缩语义" |
| 2 | **高（契约矛盾）** | 幂等 demo：keyed NOOP 不写记录，容量变化后同 key 重试执行新操作（已实跑复现），违背正文"同 key 同请求返回原 operation" | demo 记录 NOOP 决策并逐字重放；指纹扩为 (model, target, timeout_secs)；+3 回归测试 10/10 绿；重新生成 json/html | `3c381d6`；RFC L34/L51 同步 |
| 3 | 中（歧义） | current/ready/资源占用三口径混写，"未发布候选不计入"与"清理未决仍计入"矛盾 | 六行状态表，与 demo `current`/`ready` 属性逐行对齐 | `b894c06` |
| 4 | 中（过度要求） | 把我方需求（admission lease、drain fence）写成"Task 3 必须提供的公共契约"；#71 实未承诺；registry_epoch 与"不做 Manager 重启恢复"矛盾 | 按承诺归属分列（#71 已承诺 / 需导师裁决缺口）；固定两 PR head；删 registry_epoch | `b894c06`；#71 正文、#347@7813d61、#356@375ed00 快照核对 |
| 5 | 中（语义缺口） | 503 无安全重试标记；drain 证明无接口与 generation 过滤；reconcile 无退避/延续语义 | `rejected_before_accept` 标记；drain 确认接口按 victim generation 过滤；reconcile 延续原 operation + Manager 指数退避 + shutdown 兜底 | `b894c06` |
| 6 | 中（未定义） | PARTIAL 无定义；多副本失败语义未写明 | PARTIAL=本次操作部分成功（≠系统有可用副本）；多副本逐个创建、首败即停 | `b894c06`；与 demo L171 行为一致 |
| 7 | 中（活性风险） | "任一必要字段缺失即暂停全部自动扩缩"——空闲窗口/新副本无 TTFT 样本会永久停摆 | 四态区分：有效/有效零负载/观测未满/无效；聚合口径随 /conditions 暴露；验收加对应场景 | `b894c06` |
| 8 | 中（接入缺失） | 无文件级接入图与 recipe 验收计划；"等 Task 3"阻断一切 | 四行改动点表（genrm.py 现状无 scale 端点、autoscaler 仅单 rollout_service_url、metrics_collector 零填充）+ 可独立推进清单 + 文本 recipe 计划 | `b894c06`；本地代码核对 |

### Task 11（RFC #357）— RFC 口径已修订；不代表真实 Relax 接入完成

| # | 严重度 | 问题 | 修复 | 证据/commit |
|---|---|---|---|---|
| 1 | 中（接入依据不足） | 未对比 #363 的 config.timers 注入路线 | 写明 Relax 三处置 None（model.py:430/974/1449）、#363 路线（自报 22 调用点，未本地核实）、trace 核定优先 | `2f9bbf3` |
| 2 | 中（契约歧义） | "至少两个等价 peer"歧义（含不含目标？）；demo 单对照却产出结论；vpp_rank 在累计口径下无定义 | 改为"cohort ≥2 成员=目标+≥1 对照"，demo 标注置信下界；vpp_rank 声明为 schema 占位；MoE cohort 规则 defer | `2f9bbf3`；demo diagnosis.py:108 事实 |
| 3 | 中（承诺/实现混淆） | collector 大量细节只有承诺 | demo 已实现（去重/乱序/缺报/关窗）与设计承诺（独立服务/HTTP/TTL/重启）分列；GIL/序列化成本标注未隔离测量 | `2f9bbf3`；代理 D 逐项核对表 |
| 4 | 中（预算缺失） | 无规模化资源预算 | 实测 248 B/report（EVIDENCE.md:81）+ 作业级公式 + 四档实测计划，不预填 | `2f9bbf3` |
| 5 | 低（已基本诚实） | GPU 区间 vs CPU 停顿、采样盲区未明说 | 补并列展示原则、短暂异常漏采、根因按假设表述 | `2f9bbf3` |
| 6 | 中（门槛归属错误） | 3 会话/99% 覆盖率写法易被读成官方要求 | 标注为我方门槛（严于官方 <0.5%）；加 A/A、启动/稳态分开、step 自相关说明 | `2f9bbf3`；官方要求原文只有 <0.5% |
| 7 | 低（场景不全） | 注入场景仅三类 | 列全：无注入/轻微/明显/短暂/持续/恢复/工作量不均/host stall/通信/缺报乱序 + 检出率/误报/延迟/undetermined | `2f9bbf3` |
| 8 | 中（回避对比） | 未回答"为什么不用 #363 的进程内汇总" | 取舍节新增：代价/收益 + 成本未实测 + 允许收敛为进程内汇总的结论 | `2f9bbf3` |

---

## C. 修订后的 RFC

- `TASK4_RFC_GITHUB_ISSUE.md`（本地 `b894c06`、`bc0311f`）
- `TASK11_RFC_GITHUB_ISSUE.md`（本地 `2f9bbf3`，已同步至 task11 分支 `2bac8fa`）
- demo：`3c381d6`（幂等修复 + 重新生成的 contract-demo.json/html，含 2 个新 check，10/10 测试）

## D. 实测主张与来源版本对应表

| 主张 | 来源/版本 | 核验方式 | 状态 |
|---|---|---|---|
| ScaleOutStatus 无 COMPLETED/RUNNING，终态成功=ACTIVE | main `353ea7ce` rollout.py:244-331 | 亲读代码 | 已证实 |
| Autoscaler 扩容终态集合 {ACTIVE,PARTIAL,FAILED,CANCELLED} | main scaling_decision.py:24-25 | 亲读代码 | 已证实 |
| keyed NOOP 重放修复后不再执行新操作 | 工作区 demo（现 `3c381d6`） | 实跑 unittest 10/10 | 已证实 |
| #347 AdmissionGate.close() 取消在途请求 | PR #347@7813d61 | 代理核对补丁源码 | 已证实（引用代理，建议发布前抽查） |
| #356 无逐请求 admission 记账 | PR #356@375ed00 | 代理核对补丁源码 | 已证实（同上） |
| metrics_collector 零填充 | main metrics_collector.py:~460 | 亲读代码 | 已证实 |
| v4 双卡 0.116%/0.146%、off/off −0.211%、smoke 0.321%、144/144、224/224、19 测试 | EVIDENCE.md 各 pinned 快照（7718e036/caa87c0/fb5eb18/当前） | 代理从原始 JSON 重算 + 实跑测试 | 已证实（数字均可从公开数据复算） |
| #363 复用 22 处 timer 调用点、Gloo all-gather 每 10 步 | PR #363@91b58bef | 转述自 #363 正文与 bot 评审，未读其代码 | **未独立核实**（RFC 中已标注"自报"） |
| GenRM 弹性在 main 未实现 | main | 亲读 genrm.py（无 scale 端点） | 已证实 |
| 本地 Task 4 生命周期安全边界 | task4-integration dirty worktree（未提交） | CPU 组件/状态机回归 51 项；尚无真实 Ray/GenRM GPU 验证 | 部分已证实，不能发布为验收完成 |
| 248 bytes/report | EVIDENCE.md:81 初始短试 | 转引，口径已在 RFC 标注 | 已证实（口径受限） |

## E. 最小真实接入计划与待授权改动

**Task 4**（详见 RFC「接入路径」）：
1. `relax/components/genrm.py` 增 scale API（复用 ScaleOutStatus/ScaleInStatus）——**需授权改 production code**
2. `autoscaler_service.py` 多服务目标 + GenRM 独立阈值——需授权
3. `metrics_collector.py` 逐字段 validity——需授权（独立改进，双向受益）
4. 文本 recipe 验收（单机 GenRM 打分模型，1→2→1 取证）——需 GPU 资源
5. 不依赖授权即可继续：契约 demo 扩展、验收脚本编写

**Task 11**：
1. 短 trace 核定 Megatron timer 调用点覆盖（需装 Megatron 的环境）
2. 试点注入非阻塞 timer 或 schedule 插桩——需授权
3. rank→collector 数据面 + MetricsService——需授权
4. recipe 对照实验（AB/BA、off/off、A/A）——需 GPU

## F. 公开同步状态

- **未发布**。本地新 commit：task4 分支 4 个（`3c381d6`…`2f9bbf3`）、task11 分支 1 个（`2bac8fa`）；公开分支 `codex/rfc-visuals` 仍为 `2075f8d`，Issue 正文未更新。
- **剩余原因**：推送与 Issue 更新需用户明确授权（既有约束：仅本地 commit，不主动 push）。
- 发布所需步骤（待授权后执行）：① 推送两分支或合并到公开分支；② 更新 #351/#357 正文；③ RFC 内 12 处图片/demo 链接从 `7159d909` 重新固定到新 commit；④ `contract-demo-preview.jpg` 为旧页面截图，新事件加入后建议重新截图（HTTP 200 不代表视觉正常，需实际渲染检查）。

---

### 未验证风险（单列，非已确认 bug）

1. #363 的 22 处调用点与 Gloo 汇总细节未读其代码核实，RFC 中以"自报"引用。
2. Task 4 接入图基于 main `353ea7ce` 快照；#347/#356 若合入会改变 Task 3 边界结论。
3. Task 11 的 8/64/256/1024 四档 collector 成本、HTTP 传输成本、GIL 影响均未实测（RFC 已标注）。
4. Autoscaler CPU 套件在 `/root/autodl-tmp/venv-e2e` 已跑通 118 项，但仍有 Ray Serve/Pydantic 警告；不替代真实 Ray/GenRM GPU E2E。

---

## 2026-09-24 晚间增量（Task 11）

Task 11 当晚补跑 4 会话 A/A 对照实验（task11 分支 `1e29727`、`c94071b`，已推送，远端 `shanyulu/contrib/task11-straggler-analysis` 与本地 `c94071b` 一致；issue #357 正文已更新）。关键数字已由收尾核验从原始 JSON 复算；口径问题与未验证项单列。

### 已验证

- **A/A 对照实验已执行**：同协议 4 会话 × 4 对双臂全开 A/A 对照（`--aa-pairs 4`；每会话 24,160/24,160 样本、零丢弃、零 loss 差异、零参数错配，均从 `aa-session-{A,B,C,D}.json` 复算证实）。合并 A/A 中位数 +0.0135%、bootstrap mean 95% [−0.333%, +0.173%]；off/off 空对照漂移最高 +3.00%（16 对合并中位 +0.2130%）——观测器自身计时偏差与零不可区分，测量散布以环境漂移为主。
- **A/A 会话 off/on 配对开销合并**：中位数 +0.1844%、bootstrap mean 95% 上界 +0.7061%，仍高于 0.5% 官方门槛，验收计划（recipe 实测）不变。两数可从 A/A 会话 16 个 off/on 配对复现（多种子 bootstrap 上界 +0.699%~+0.712%，含 +0.7061%）。
- **工具与数据入库**：`--aa-pairs` 已加入 run_demo.py；原始数据入库 `results/multisession-20260924/aa-session-{A,B,C,D}.json` 与 `results/aa-smoke.json`。
- **RFC #357 证据表已更新 A/A 行并重新发布 issue 正文**（gh api 核对：#357 body 的 A/A 行与本地 TASK11_RFC_GITHUB_ISSUE.md 逐字一致）。
- **本地测试**：`python -m unittest discover -s demos/task11_straggler -p "test_*.py"` 19/19 通过、0 跳过（torch 2.8.0+cu128、CUDA 可用，5 个 CUDA 条件 probe 测试实际执行）。A/A 两次 commit 未新增测试文件，测试数仍为 19（EVIDENCE.md 记载同为 19）。

### 未验证 / 口径注记

- **“32 对”标注与数据不符（RFC 与 EVIDENCE 同源）**：两份文档均把 +0.1844% / +0.7061% 标为 “32 pairs / 32 对”，但复算表明该中位数与上界对应 A/A 会话的 **16 个 off/on 配对**（16 对 × 2 臂 = 32 个计时 trial，疑为口径混写）。若把 16 对 A/A（双臂全开、差值纯为噪声，方法学上不应计入开销池）并入成 32 值，中位数为 +0.0785%、bootstrap 上界约 +0.36%（< 0.5%）；“仍超 0.5%” 的结论仅对 16 对 off/on 口径成立。已报告原文作者，未修改原文。
- RFC A/A 行两处数字为 EVIDENCE 4 位小数的 3 位舍入（[−0.333%, +0.173%] vs [−0.3332%, +0.1728%]；+3.00% vs +3.0036%）：数值一致、非逐字一致（舍入本身正确）。
- A/A 仍限于双卡 standalone demo 协议（2×RTX 4090，steps 8000 / interval 8 / batch 48 / dim 1024），非 Relax recipe；观测器偏差结论不可外推到其他配置。

### 复现命令

```bash
cd demos/task11_straggler && python run_demo.py --gpus 2 --pairs 4 --null-pairs 4 --aa-pairs 4 --steps 8000 --injection-steps 128 --warmup 12 --interval 8 --batch 48 --dim 1024 --output results/xx.json
```

参数已与 `aa-session-*.json` 内记录的 config 逐字段核对一致（`injection_steps 128` 等全部吻合）。

---

## 2026-09-24 深夜增量（Task 4：真实 GPU E2E）

### 已验证（真实 Ray 2.58 + SGLang 0.5.5.post3 + Qwen3-0.6B，4×4090）

| 项 | 结果 | 证据 |
| --- | --- | --- |
| 手动 1→2→1 全生命周期 | **E2E_PASS**：扩容 `CREATING→HEALTH_CHECKING→ACTIVE`（45s）、缩容 `DRAINING→COMPLETED`（1s）；初始引擎存活、恰好移除弹性引擎；三阶段贪心打分逐字一致；4,163 负载请求零失败（扩容窗 2,434 / 缩容窗 52）；GPU 显存与 Ray 空闲 GPU 归还基线 | `demos/task4_genrm/results/e2e_run_20260924`（task4-integration 分支 commit a2ca6cb） |
| Autoscaler 自动扩容 | HIGH 负载 60s 内自动 1→2（token_usage_high 触发）；弹性引擎实际服务 520 请求；36,931 请求零失败 | `autoscaler_run_20260924`（scale_out ACTIVE 入 history） |
| Autoscaler 自动缩容 | **未通过**（第一次运行）：per-service cooldown 不在 ServiceScalingPolicy 内，全局 300s scale-in cooldown 超出 LOW' 观察窗 | 已定位根因；v2 运行中（运行时 PATCH cooldown 60s + 窗口 500s） |

### 过程中修掉的真实 bug（全部先在 E2E 中暴露、后修复、均有 commit）

1. `wait_for_ready` 在 ray 2.5x 的 `ray.util.placement_group` 不存在 → 改 `pg.ready()+ray.wait`（a7186ca）
2. scale-out PG 返回本地 GPU 索引 0 而非物理 GPU id → 弹性引擎与初始引擎同卡 OOM → InfoActor 探测（edad49e）
3. Serve 代理容器内只绑 localhost → URL 重写 127.0.0.1（55bf992）
4. autoscaler E2E 三个 API 层 bug（`get_deployment_handle` 误用、`DeploymentResponse` 不能 `ray.get`、`/scale_history`/`/conditions` 缺 `service=genrm` 导致必误判）（d9802b6）
5. HIGH 负载不饱和（短 prompt 低占用；相同 prompt 被 radix cache KV 共享）→ 长上下文 + 唯一前缀（6eeea72、17a1776 前序）

### 环境事实

- sglang 版本链：PyPI 0.5.17 需 torch 2.11（与 relax docker 的源码版不同）；**0.5.5.post3 是唯一精确匹配 torch 2.8.0 的版本**，`ServerArgs`/`launch_server` API 面与 relax 引擎代码兼容（探针验证 + E2E 验证）
- 官方 judge（Qwen3-VL-30B-A3B × 8 GPU）本机不可承载；E2E 以 Qwen3-0.6B 验证生命周期/路由/一致性语义
- 数据集 dapo-math-17k 已就位（训练 E2E 用）
