# 3090 参数测量

## 当前结论

参数门禁 **PASS**：两对各 182 个张量结果均通过，违规和缺失容差均为 0。四臂训练、串行转换、正式比较和归档完整性核验均已结束。此结论仅覆盖本次最终 checkpoint 在冻结 OFF/OFF 包络内的比较。

| 检查       | 结果与边界                                                                       |
| ---------- | -------------------------------------------------------------------------------- |
| 产品       | `927c5de2f5a8f307cad0c87f2c7eb2b78262334d`，未修改 production code               |
| 预注册顺序 | M1-OFF → M1-ON → M2-ON → M2-OFF；各执行一次                                      |
| 四臂训练   | SUCCEEDED、valid、资源归还；各 48 次更新，原生数值检查无 NaN/Inf                 |
| 配对控制   | 两对 step ID 与 token 序列分别一致；不以此替代参数比较                           |
| OFF 控制   | `submit.log` 明确记录 profiler disabled；无 observer envelope                    |
| ON 控制    | 每臂 2,112 条有效设备测量，四 rank 各 528 条；runtime 已启用，collector 计数吻合 |
| 观测器健康 | 已记录的错误、丢弃及 readout timeout 均为 0；检查定义在首个 ON 前提交            |
| 转换与清单 | 每臂 182 个唯一张量键；原始 DCP、raw/sanitized 转换和 NPY payload 均保留         |
| 参数判定   | PASS：两对各 182/182；正式工具退出 0，未重跑、未改容差                           |

`P_CONTROL_AUDIT.json` 记录控制检查与原始文件哈希，已用归档审计源码从原件独立重算，结果逐字节一致；`P_MEASUREMENT_RAW_LEDGER.json` 记录四臂 checkpoint、转换、清单和日志来源。每对 OFF/ON 标签按 treatment 固定，BA 仅表示执行顺序。

正式结果 `P_MEASUREMENT_RESULT.json` 的文件 SHA256 为 `d9f2e043ecbd0ebe86a51aeea2e69b051b32f95e16fb55b5b406d9875d45cb1c`，自哈希为 `06dca1126450fa4376f7b7aa99f03bc8487a5b6332a2d52885637fc77fbf7c8e`。`P_COMPLETION_AUDIT.json` 复核产品、执行锁、结果、校准/容差绑定、配对清单及压缩归档，所有归档成员与原件字节一致。

## 版本与门禁

校准结果在 `7237e1c` 提交，measurement lock 在 `4c9d9df` 提交，执行源码锁及 observer 生效门禁在 `4c74209` 提交；均早于首个 ON。13 个浮点张量沿用 OFF/OFF 校准的 `2 × max(两次最大绝对差)` 容差；169 个非浮点空占位张量精确比较。

bounded executor 逐张量读取并累计极值，不构造全量差值列表；正式 CLI 复用原 runner 的四臂、身份与 checkpoint lineage 检查。原 comparator、runner、adapter 和 protocol 没有改动。工具回归为 60 passed，小型用例的新旧输出字节一致；不声称在这台机器上同时跑过原版全量 eager executor。

训练完成后，转换、inventory 生成和比较依次执行；没有训练与后处理重叠，没有并发 cache eviction。GPU 已回到 1 MiB 基线。Ray session 与校准不同，补充身份见 `measurement/RAY_HEAD_OWNERSHIP.json`；该文件是 bootstrap 请求记录的脱敏副本，保留原文哈希，不是独立健康断言。此次实际启动早于持久 bootstrap helper 的最终提交，不能倒写启动源码归属。

比较进程已正常结束。只读监控得到 276 个运行采样，采样 RSS 峰值 47.72 GiB，整个 cgroup 采样峰值 187.98 GiB，上限 360 GiB；观察区间内 max、OOM、OOM-kill 等事件增量均为 0。监控在比较启动后才加入，因此不将采样峰值宣称为完整生命周期峰值。原始采样及监控源码保存在 `measurement/`。

## 复算

在包含本次证据的 checkout 根目录执行。`CAMPAIGN` 必须指向完整原件，而非仅有小型清单的归档目录；输出必须使用不存在的新路径。

```bash
CAMPAIGN=/root/autodl-tmp/task11-3090/formal/parameter-measurement-4c74209
BASE=evidence/gpu_campaign/task11_3090/c2_parameter
python3 evidence/tools/c2_parameter_execution_lock_927c5de.py verify \
  --repo "$PWD" --lock "$BASE/locks/P_EXECUTION_LOCK.json"
python3 "$BASE/measurement/audit_controls_original.py.txt" \
  --campaign "$CAMPAIGN" --gate "$BASE/OBSERVER_ENACTMENT_GATE.md" \
  --out "$CAMPAIGN/P_CONTROL_AUDIT_REPLAY.json"
cmp "$BASE/P_CONTROL_AUDIT.json" "$CAMPAIGN/P_CONTROL_AUDIT_REPLAY.json"
python3 evidence/tools/c2_parameter_bounded_927c5de.py \
  --lock "$BASE/locks/P_MEASUREMENT_LOCK.json" \
  --campaign "$CAMPAIGN" \
  --calibration-result "$BASE/P_CALIBRATION_RESULT.json" \
  --pair-manifest "$CAMPAIGN/P-M1_PAIR_MANIFEST.json" \
  --pair-manifest "$CAMPAIGN/P-M2_PAIR_MANIFEST.json" \
  --out "$CAMPAIGN/P_MEASUREMENT_RECOMPUTED.json"
```

移动原件时须保留 checkpoint/转换/payload 的完整相对布局，并按工具的原始 lineage 规则核对路径；不得手改已哈希清单以绕过门禁。`measurement/*_PAIR_MANIFEST.json` 是执行记录的字节副本，不代表仓库已经包含其指向的 NPY。

## 归档与限制

`measurement/<arm>/` 保存 manifest、inventory、adapter record，以及包含原始训练/提交/转换日志的 `raw_logs.tar.gz`。日志含原生 ANSI 和空白，压缩保存，不以格式化破坏原文哈希。两个 ON 臂的 `observer_raw.tar.gz` 保存完整 observer JSON/JSONL；原文件通过 gitleaks 8.30.1 扫描，均无发现。解压后可按 `P_CONTROL_AUDIT.json` 和原始台账核对原始哈希，不用压缩包哈希替代原文哈希。

大 checkpoint 与 payload 仍只在本机保留，尚未获得公开归档渠道：本地可复算，公开复算未闭环。参数 verdict 只覆盖本次最终 checkpoint 的冻结包络比较，不证明位确定性、全过程轨迹等价、整体 C2 或 Task 11 完成。C1 confirmatory 未启动；C3 与范围裁决不在本次实验内，旧 overlap NOT_PASS 不改写。

新增文件提交检查通过，相关工具回归 60 passed。全量 pre-commit 在隔离副本执行：历史 `manifest.py` 的 C416、`run_abba_sessions.py` 和 `straggler_startup_decompose.py` 的三处 F841，以及 `LATENCY_REPORT.md` 的 mdformat 渲染校验失败仍在；不是全量绿。历史证据格式化不迁回本仓库。检查日志在 `/tmp/codex-task11-precommit.ZZLmCA/full-check-final-verdict.log`，SHA256 为 `04bb71b4e74d4daa41cdbe585a62750f17c76dd81fc1cde9d6e5cd7bd16a21c7`。
