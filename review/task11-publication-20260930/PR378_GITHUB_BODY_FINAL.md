## 改动目的

为 Megatron RL 训练增加默认关闭的慢 rank 诊断。实现沿用 timer 挂点，记录 host/CUDA stream 区间，在后台读回设备事件，按拓扑、阶段和工作量比较 rank，并将阶段级 JSONL 与 rollout 级确认指标写入现有平台路径。设计和边界见 [RFC #357](https://github.com/redai-studio/Relax/issues/357)。

## 当前状态

| 项目       | 结果                                                                                                |
| ---------- | --------------------------------------------------------------------------------------------------- |
| PR 头      | `c2875a5`，Draft；当前公开头仅修复 Python 3.10 测试竞态，`relax/` 产品文件零变更                    |
| CI         | 当前头 8/8 通过                                                                                     |
| C1         | `e961661` pilot 为 `INCONCLUSIVE`：均值 +0.417%，95% CI 上界 +2.023%；待主指标裁决及固定 N 确认实验 |
| C2         | a48a23b 旧 loss/grad `UNSCORED`；927c5de 参数、overlap、新 loss/grad 补验均按各自协议单列           |
| C3         | 公开输入包可在本地独立重算；实时 cadence 待裁决，逐事件时延 `UNMEASURED`                            |
| 维护者决定 | C1 主指标、rollout cadence 是否满足实时、Attention/MoE 是否要求实际插桩                             |

PR 保持 Draft。CI 只证明当前代码头的回归检查通过，不替代性能、数值等价或平台验收。

## 实现审查路径

```mermaid
flowchart TB
  M["Megatron timer shim"] --> O["Observer<br/>上下文 / 有界队列"]
  O --> R["后台 CUDA event 读回"]
  R --> C["global rank 0 Collector"]
  C --> D["Detector<br/>参照集合 / 连续状态"]
  D --> J["阶段 JSONL"]
  D --> T["rollout 摘要 → TensorBoard"]
```

| 文件入口                                                                                                                                                                                                                                                                                     | 审查重点                                                                    |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| [Megatron timer shim](https://github.com/redai-studio/Relax/blob/c2875a5c219fcef38011ea93ce617b74a8efef08/relax/utils/straggler/megatron_timer_shim.py) 与 [observer](https://github.com/redai-studio/Relax/blob/c2875a5c219fcef38011ea93ce617b74a8efef08/relax/utils/straggler/observer.py) | timer 上下文固定在区间结束时；CUDA event 后台读回；host-only 顺序及退化路径 |
| [collector](https://github.com/redai-studio/Relax/blob/c2875a5c219fcef38011ea93ce617b74a8efef08/relax/utils/straggler/collector.py) 与 [detector](https://github.com/redai-studio/Relax/blob/c2875a5c219fcef38011ea93ce617b74a8efef08/relax/utils/straggler/detector.py)                     | 可比集合、覆盖率、窗口连续性、unknown 与 recovered 的边界                   |
| [reporter](https://github.com/redai-studio/Relax/blob/c2875a5c219fcef38011ea93ce617b74a8efef08/relax/utils/straggler/reporter.py) 与 [回归测试](https://github.com/redai-studio/Relax/tree/c2875a5c219fcef38011ea93ce617b74a8efef08/tests/utils/straggler)                                   | 平台字段归属、flush/readback、故障隔离、Python 版本行为                     |

Collector 位于 global rank 0 训练进程内，不是独立服务；未配置共享地址时只能本地汇总。CUDA event 是 stream 可观察区间，可能包含等待，不能解释为纯 kernel/NCCL 时长。host-only 模式下部分交付可能在调用线程执行。默认 5 秒窗口不构成平台 SLA。

## 验收摘要

| 项目                     | 证据版本                                      | 判定                                                                                                                                                                                   |
| ------------------------ | --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C1 性能开销              | `e961661`，6 对 pilot                         | `INCONCLUSIVE`；+0.417% 点估计，95% CI 上界 +2.023%，未证明 `<0.5%`                                                                                                                    |
| C2 旧 loss/grad          | `a48a23b`                                     | `UNSCORED`；首个 ON 前没有冻结容差，本次新补验不回溯改写                                                                                                                               |
| C2 参数                  | `927c5de`，本地记录 `116d527`                 | **本地 PASS，未公开复算**；每对 13 个有内容浮点组按冻结数值包络通过，169 个空占位项匹配；每对 48 个非张量叶中 47 个一致，唯一差异为含运行态路径/名称/TransferQueue ID 与端口的 args 叶 |
| C2 overlap               | `a48a23b` 与 `927c5de` 独立                   | 旧 a48a23b `NOT_PASS` 保留；927c5de 新预注册门槛下 `PASS`，不能覆盖旧结果或证明零影响                                                                                                  |
| C2 native loss/grad 补验 | `927c5de`，4 OFF 校准 + 两对 OFF/ON，48 步/臂 | `PASS_WITHIN_OFF_OFF_ENVELOPE`：loss 差 0.050019/0.048279，限值 0.233478；grad 差 8.38410/12.53071，限值 57.43427                                                                      |
| C3 慢 rank 定位          | `927c5de`，evidence `7098b43`                 | 健康臂 37 uncertain、0 确认告警；rank 3 四个阶段标签命中 4 次、最大 6.869×；3 条非目标告警按冻结窗口代理规则归类，成因未证实                                                           |
| C3 平台确认              | `927c5de`，同一公开输入包                     | TensorBoard rollout 级确认 rank 为 3、3、2、2；与 JSONL 无逐事件 ID，不能报告端到端时延；实时性待裁决                                                                                  |

新 native loss/grad 补验使用 4 个 OFF 臂的六个共享对照冻结两项阈值；每对需满足 48 步、有限数值及 step/token-volume/LR/update 序列门槛。PASS 只说明两对本次 loss 与 grad norm 位于同版 OFF/OFF 包络内，不证明 bit determinism、样本内容/顺序相同、准确率不变或整体 C2 完成。工具、协议和原始日志仍为本地证据，未发布为可访问的 evidence ref。

![已公开 overlap trace 的独立复算索引](https://github.com/shanyulu/Relax/tree/7098b43/evidence/gpu_campaign/c2p-927c5de/trace_dp4)

此链接指向已有公开的 32 件 overlap trace 和台账；本轮 loss/grad 原始日志与 checkpoint 不在该目录，不能借此暗示其已公开。

## C3 复算与待审自然告警

C3 使用 `7098b43` 的公开输入包；公开台账内 11 个直接对象及 18 个归档成员共 29 项哈希匹配。独立分析在本机临时目录运行，JSONL 分类及 TensorBoard 提取结果与冻结结果一致。公开包内日志已脱敏，原始日志哈希及转换关系另有记录。因此这里的“公开输入可复算”指数据可下载、在本地成功重算，并非复算在 GitHub 执行。

减速臂的三条非目标告警按冻结窗口代理规则分类为误报；这个标签不证明成因。两条无延迟注入的 observer-on 运行有 4,011 行 observer envelope，复放后重现七条已保存确认告警，告警原因未知；完整 cohort 覆盖，记录的 token/sequence/microbatch 量接近。六条保存了后续恢复，M1/r2 `forward-compute` 未保存恢复，快照时仍 active。这些是测得的计时异常，不能称为误报或硬件故障。

| Arm / 窗口 | Rank / 阶段                |                host 比值 |          CUDA event 比值 | 保存的恢复      |
| ---------- | -------------------------- | -----------------------: | -----------------------: | --------------- |
| M1 / w16   | r2 `forward-compute`       |                   1.145× |                   1.148× | 无；快照 active |
| M2 / w11   | r1/r2/r3 `forward-compute` | 1.292× / 1.222× / 1.302× | 1.298× / 1.230× / 1.310× | w13 / w14 / w12 |
| M2 / w11   | r2/r3 `forward-backward`   |          1.080× / 1.126× |          1.018× / 1.017× | w12 / w12       |
| M2 / w15   | r3 `forward-compute`       |                   1.288× |                   1.293× | w16             |

五个额外 crossing 只在离线 flush 非终态原始尾窗时出现，不是 live collector 保存的确认告警。两个 runtime status 都是 `closed=false`、仍有两个 open windows；M1 有 6 个待读回、M2 有 1 个，collector status 早于作业完成。现存状态计数为零，不等于完成关窗后的最终零丢弃证明。

![Observer-only 运行中的自然告警、恢复及尾窗复放候选](../../evidence/gpu_campaign/task11_3090/native_loss_927c5de/NATURAL_ALERT_REVIEW_20261001.svg)

逐告警窗口、rank、参照比值和原件哈希见本地提交 `4e4e736878e5328e7c59f39d21fdceea1046a430` 中的 `evidence/gpu_campaign/task11_3090/native_loss_927c5de/NATURAL_ALERT_REVIEW_20261001.md`，复放脚本为 `evidence/tools/replay_native_loss_alerts_20261001.py`。脚本 SHA-256 为 `efff2163…d7b16c`；新增 12 项测试验证 job-log/raw-file 哈希、重复 JSON 键与 envelope 身份拒绝，以及 raw-root symlink confinement。报告、图和原始数据仍未公开，正文发布前须替换为不可变 URL。

## 公开证据边界

当前公开 C3 输入包与 overlap archive 固定于 `7098b43`。native loss/grad 与门禁审计固定于本地 `233e5f8`、`e8d200a`；自然告警报告和加固后的复放脚本固定于本地 `4e4e736`；参数记录 `116d527` 经 GitHub API 返回 404。它们尚非公开可下载、可复算的证据；原始 checkpoint 也未公开，哈希 ledger 不能替代原件。整体 Task 11 仍需主指标裁决与 C1 确认实验、C3 实时性裁决、Attention/MoE 范围决定，以及大文件的可迁移存储与下载复算。

新补验的本地源：八臂审计报告 `evidence/gpu_campaign/task11_3090/native_loss_927c5de/TOOL_GATE_AUDIT_20261001.md`（本地 commit `e8d200a8d2853448618721952ae3f703d1054aac`；37 项定向测试；审计工具 SHA-256 `b8233b8cfd35a4e422db4933e1352ba030c7c3391d5823444d2198afb9e83af1`）、判定 `evidence/gpu_campaign/task11_3090/native_loss_927c5de/measurement_verdict.json` 和协议 `evidence/NATIVE_LOSS_PROTOCOL_927C5DE_20260930.md`。该结果仅本地可读，尚未公开发布。参数图源：`evidence/gpu_campaign/task11_3090/c2_parameter/parameter_deltas.svg`。本地引用发布后须替换为真实固定地址。

![Native loss 与 grad norm 差值占各自冻结 OFF/OFF 包络比例](./native_loss_envelope_20261001.svg)

图中每个值为一对 OFF/ON 48 步序列的最大绝对差除以冻结容差。图表不是统计置信区间，四个 OFF 校准臂产生的六个对照也不是独立样本。

![最终 checkpoint 参数差值与冻结容差](../../evidence/gpu_campaign/task11_3090/c2_parameter/parameter_deltas.svg)

该图对应参数实验，不代表 native loss/grad 补验；两项结论分开解释。发布时用不可变 evidence URL 替换相对路径。
