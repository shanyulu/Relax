# Task 11 C2 — 最小真实接入规划（plan only）

> 状态：**规划文档，未改任何代码**。执行前置条件：Task 4 B2 收尾 + 导师确认首期 recipe/PP 配置 + 对 `relax/` 生产代码的明确授权。
> 依据：本机 `relax` 源码（`contrib/task4-genrm-elastic-scaling` HEAD `5d47b48`）、Megatron 源码 `/root/autodl-tmp/megatron-lm-src`、`demos/task11_straggler/`（19 项测试实跑通过）、真实 rollout fixture。每处代码事实附 `file:line`。

## 0. C2 的原始定义（与上游任务口径对齐）

Phase C 把 Task 11 拆成 C1–C5，其中：

- **C1 = 统计估计量修订**（已完成，落在 Task 11 `EVIDENCE.md` 的 *Pooled statistics revision* 与 RFC #357）：估计量统一为预声明的**配对中位数**，session-aware（层级）bootstrap，误报率带分母（`2/1/2/0 ÷ cohort-window 总数`）。这一步只改证据与口径，不接数据面。
- **C2 = 最小真实路径**（本文档）：把统一估计量接到**真实训练数据流**上——复用 Relax 三处 `config.timers = None` 挂点注入**非阻塞** timer，落地 observer + detector + collector 最小集，默认关闭 + 观测故障降级，移植 19 个 demo 测试，跑一次真实训练 smoke；收住 attention/MoE、复杂 PP、全套服务扩张项。

**口径澄清（诚实记录）**：任务分派里把 C2 描述成"统一估计量接到真实 reward 数据流"。严格看，C2 的**真实数据流是 Megatron 训练步**（forward/backward/optimizer/collective 区间），"统一估计量"属 C1。给定的 `checkpoints/task4-genrm-smoke/rollout_result/train/1.jsonl`（8 样本，`reward{score,acc,pred,judge_response,format_error}`）是 **Task 4 的 GenRM reward fixture**，不是 Task 11 profiler 的观测源。它的正确用途见 §3.3（report 层共报与真实样本 fixtures）。本规划按**原始 C2 定义**执行，避免把两件事混成一件。

## 1. 先读代码得到的硬约束

| 事实                                                                                                                                                                                                         | 出处                                                                                                                                                                                                                      | 对方案的约束                                                                                                                                                                                         |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Relax 在三处把 `config.timers` 置 `None`：优化器配置 `setup_model_and_optimizer()`、评估 `forward_only()`、训练 `train()`                                                                                    | `relax/backends/megatron/model.py:430,974,1449`                                                                                                                                                                           | 这就是 RFC 说的三个挂点；**训练挂 1449 + 优化器挂 430，评估挂 974 保持 None**（原注释 "Don't care about timing during evaluation"）                                                                  |
| Megatron 原生 `Timer.start()/stop()` **无条件调用 `torch.cuda.synchronize()`**                                                                                                                               | `/root/autodl-tmp/megatron-lm-src/megatron/core/timers.py:152,167`                                                                                                                                                        | **不能直接复用 `megatron.core.timers.Timers`**：它会在每个调用点同步 GPU，正是 RFC「不 `synchronize`、热路径禁止 GPU-CPU 同步」所禁止的。最小路径必须提供**同签名、CUDA-Event-backed 的非阻塞 shim** |
| `config.timers` 被调用：6 文件共 **106** 处、**23** 个唯一 timer 名（`forward-compute`/`backward-compute`/`forward-backward`/`optimizer-inner-step`/`all-grads-sync`/`params-all-gather`/`forward-recv` 等） | `megatron/core/{pipeline_parallel/schedules.py, pipeline_parallel/p2p_communication.py, optimizer/optimizer.py, optimizer/distrib_optimizer.py, distributed/finalize_model_grads.py, pipeline_parallel/combined_1f1b.py}` | 覆盖 forward/backward/optimizer/通信四类边界；**第一步必须用短 trace 核定实际覆盖**，够用直接复用，拆不开 forward/backward 的位置才改 MCore schedule                                                 |
| Relax 已有 `Timer` 单例与 Chrome-trace `TimelineEvent`，`log_perf_data_raw` 读 `Timer().log_dict()` 上报 `perf/*`                                                                                            | `relax/utils/timer.py:95,159`；`relax/utils/training/train_metric_utils.py:29-31`                                                                                                                                         | 聚合结果的**既有**上报通路已存在，C2 只需把汇总值并入 `perf/*`，不新建指标通道                                                                                                                       |
| 训练 actor 已在多个边界用 `timer(...)` 上下文管理器                                                                                                                                                          | `relax/backends/megatron/actor.py:1599,1678`                                                                                                                                                                              | 可与新 observer 共用挂点风格，但**不引入 GPU 同步**（现有 `Timer.start/end` 只 `time()`，无 sync——需保持）                                                                                           |
| 19 项 demo 测试实跑通过（`python -m unittest discover -s demos/task11_straggler -p "test_*.py"`）                                                                                                            | 本机实跑，task11 worktree                                                                                                                                                                                                 | 移植基线明确：`test_probe.py`/`test_diagnosis.py`/`test_replay.py`/`test_rank_view.py`                                                                                                               |
| demos 为**进程内队列**传输，非 HTTP；`probe.py` 的 Event 池/有界队列/丢包计数、`diagnosis.py` 的 cohort 等价与 `uncertain` 判定可直接移植                                                                    | `demos/task11_straggler/probe.py:35-80`、`diagnosis.py:80-147`                                                                                                                                                            | 最小集先复用进程内传输，**HTTP/MetricsService 放到 C2 之后**（RFC 已列为接入时设计，不是 demo 已有能力）                                                                                             |

## 2. 最小改动清单（一段式）

**新增 `relax/utils/straggler/`（默认关闭，纯增量，不动既有路径）**：

1. `megatron_timer_shim.py` — 实现 `MegatronTimersShim`，签名兼容 Megatron 的 `config.timers(name, log_level=None)`：返回对象具备 `start(barrier=False)`/`stop(barrier=False)`/`reset()`/`elapsed()`，内部用 `torch.cuda.Event`（预分配池）记录，**绝不 `cuda.synchronize()`**，`barrier` 参数一律忽略（避免新增 collective）。这是 C2 的技术核心。
2. `observer.py` — 从 `demos/task11_straggler/probe.py` 移植：每 rank 从预分配池取 Event、`record()`、把句柄放入**有界 SPSC 队列**；后台线程查询 `elapsed_time` 并组装最小 envelope（§3.1）。训练线程只做 `record()`。
3. `detector.py` — 从 `diagnosis.py` 移植：cohort 等价（同 TP/PP/VPP/CP/EP/ETP 位置，仅 DP/EDP 不同）、工作量 ≤5% 容差、两窗口持续性、`uncertain`（缺报/乱序/schema 不一致）；默认参数仅 demo 用，接入由 recipe 校准。
4. `collector.py` — 最小 collector：先**进程内/同机队列**收 envelope，按 `(run_id, topology_epoch, global_rank, sample_seq)` 幂等去重，按 cohort 期望成员集 + TTL 关窗；内存三重限界（cohort 数 / 待完成窗口 / 历史条数），淘汰带 drop reason。

**修改既有文件（3 处，均 gated）**：

| 文件:行                                 | 改动                                                                                 | 目的                     | 风险/约束                                                  |
| --------------------------------------- | ------------------------------------------------------------------------------------ | ------------------------ | ---------------------------------------------------------- |
| `relax/backends/megatron/model.py:1449` | `config.timers = None` → `config.timers = get_straggler_timers()`（默认返回 `None`） | 训练路径注入非阻塞 timer | 默认关闭必须保持现有行为逐位一致                           |
| `relax/backends/megatron/model.py:430`  | 同上（优化器配置）                                                                   | 激活 `optimizer-*` 边界  | 同上                                                       |
| `relax/backends/megatron/actor.py`      | actor 初始化建 observer、退出时按固定 deadline 关停                                  | 采集生命周期             | 关闭时未完成 Event 作废不回池，后台线程不得阻止 actor 退出 |

**移植测试**：`tests/utils/straggler/`，从 4 个 demo 测试文件移植（19 项基线），新增 CPU 单测覆盖 shim 语义（无 sync、池耗尽丢观测）、observer 降级、collector 幂等/淘汰。**必须全 CPU 可跑，不依赖 GPU**。

**一次训练 smoke**：复用 Task 4 的最小 recipe（`scripts/training/genrm/run-qwen3-0.6B-4xgpu-genrm-smoke.sh`）或纯文本 recipe，开 observer 跑 ≥2 step，确认 step/loss/ckpt 正常推进、coverage 与 drop reason 落盘。

## 3. 数据流

### 3.1 最小 envelope（与 RFC 一致）

```text
schema_version, run_id, topology_epoch, global_step, sample_seq,
global_rank, node_id, local_device,
tp_rank, pp_rank, vpp_rank, cp_rank, ep_rank, etp_rank, dp_rank, edp_rank,
stage_schema, workload{tokens,sequences,microbatches}, stages_ms{}, recorded_at
```

`(run_id, topology_epoch, global_rank, sample_seq)` 为幂等键。窗口按 optimizer step 对齐。

### 3.2 链路

```text
MCore config.timers(shim)  ── 训练线程只 record() ──▶  Event 池 + 有界 SPSC 队列
        │                                                     │
        └─ 不 sync、不新增 collective                   后台线程 query/readout
                                                              ▼
                                              collector（幂等去重 + cohort 关窗 + 淘汰）
                                                              ▼
                              detector（等价 cohort/工作量/持续性 → alert | uncertain）
                                                              ▼
                          聚合结果并入既有 relax/utils/training/train_metric_utils.py 的 perf/*
```

### 3.3 真实 fixture 的正确用途

`checkpoints/task4-genrm-smoke/rollout_result/train/1.jsonl`（8 样本，`reward{score,acc,pred,judge_response,format_error}`）：作为 **report 层的真实样本 fixture**——验证"聚合结果与真实 reward 字段在同一 step 上共报"（例如 `perf/*` 与 `reward/score` 同 step 出现），以及为 `recorded_at`/`workload` 提供**真实数值**样例（`response_token_count`、`total_token_count` 均真实存在）。只读输入，不在本目录写入。

## 4. 验收标准（对准官方三项）

1. **开销 \<0.5%**：用 C1 的统一估计量（配对中位数 + 层级 bootstrap 95% 上界）在**真实 recipe** 上测量，计入后台查询/序列化/collector 成本；启动段与稳态段分开报告；AB/BA + off/off + A/A 三对照；≥3 新进程会话、覆盖率 ≥99%。
2. **不影响精度与 overlap**：对照 loss、参数逐位/容差一致；短 trace 确认未破坏既有通算 overlap，容差事先写进 manifest。
3. **实时上报、便于定位**：展示 rank/阶段/cohort、覆盖率、drop reason、采样→可见延迟；注入场景（无注入对照、轻微/明显变慢、短暂/持续、恢复、工作量不均、host stall、通信等待、缺报乱序）报检出率/误报/延迟/`undetermined` 占比。
4. **观测失败不伤训练**：注入 Event 池耗尽、队列满、collector 超时/重启、乱序/重复包、退出未完成 Event；step/loss/ckpt 继续推进。

判定规则沿用 RFC：同 cohort、同 stage set、工作量差 ≤5%，连续两窗口满足 `observed/peer ≥ ratio` 且 `observed − peer ≥ absolute_ms`；缺报/乱序/stage 不一致进 `uncertain`。

## 5. 明确收住（C2 不做）

- attention/MoE 真实挂点（仅保留关闭态 schema capability）。
- 复杂 PP/VPP>1 的 chunk 级定位（`vpp_rank` 仅占位）。
- 批量 HTTP 传输、独立 CPU-only 服务、服务发现、collector 重启恢复。
- 与 MetricsService 的深度耦合（C2 只并入既有 `perf/*`）。
- 踢卡/调参等任何影响训练的动作。

## 6. 授权与外部依赖（Ask First）

- **需授权**：新增 `relax/utils/straggler/`、改 `relax/backends/megatron/{model,actor}.py`（AGENTS.md「Ask First」覆盖 Controller/Service/生产代码）。
- **需导师确认**：首期 recipe 与 PP 配置；独立 CPU-only collector 的接入方式（RFC 已挂此问题）。
- **与 #363 边界**：若维护者选 #363 路线，本方案收敛为增量贡献（采集故障隔离 + 诊断验证）。

## 7. 未验证 / 风险（单列，不包装为已确认）

1. **挂点覆盖未核定**：106 处 `config.timers` 对 forward/backward/optimizer/collective 四类边界的实际覆盖，必须先用短 trace 测量；本机 **未跑**该 trace。
2. **shim 的 `barrier` 语义**：忽略 `barrier` 会改变 `barrier_with_L1_time` 下的计时口径（原带 barrier 的点会变快），需在 trace 阶段确认是否影响阶段归属。
3. **开销数字来源受限**：现有 0.116%/0.146%、0.0861% 等均来自**双卡 standalone demo / 玩具训练循环**，非 Relax recipe，不能外推。
4. **GIL 与序列化成本未隔离**：后台 sender、Event query、序列化的独立成本无测量。
5. **真实 fixture 仅 8 样本**：作为 fixture 足够，不足以支撑精度/一致性统计结论。

## 参考

- 官方 Task 11：`community/contributor-program/2026-cohort-2/official-task.md`（开销 \<0.5%、不影响精度/overlap、实时上报）
- RFC #357 · Task 11 `EVIDENCE.md`（C1 统一估计量、多会话/A/A、口径限制）
- `demos/task11_straggler/`（observer/detector 机制基线与 19 项测试）
- Megatron 计时器接口：`megatron/core/timers.py:109-175,217-260`
