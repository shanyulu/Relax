# 四份 Issue/PR 正文发布索引（2026-10-01）

这组文件是本地中文正文候选；没有改动 GitHub。来源工作区从本地提交 `233e5f8` 创建。四份正文均应在证据发布完成后整体同步，不把本地 SHA 写成可访问的 GitHub 链接。

| GitHub 项目      | 正文源文件                                                       | 远端基线                                 | 产品 / 证据基线                        | 当前远端状态                                                        |
| ---------------- | ---------------------------------------------------------------- | ---------------------------------------- | -------------------------------------- | ------------------------------------------------------------------- |
| Task 4 RFC #351  | [ISSUE351_GITHUB_BODY_FINAL.md](./ISSUE351_GITHUB_BODY_FINAL.md) | 当前 Issue 正文；关联 PR `da4acbb`       | 产品 `0481701`；证据 `fdf288d`         | OPEN；artifact、验收规模、采样语义待维护者裁决                      |
| Task 4 PR #370   | [PR370_GITHUB_BODY_FINAL.md](./PR370_GITHUB_BODY_FINAL.md)       | head `da4acbb`                           | 产品 `0481701`；证据 `fdf288d`         | OPEN、非 Draft、mergeable；8 项必需 CI 成功；review approval 未取得 |
| Task 11 RFC #357 | [ISSUE357_GITHUB_BODY_FINAL.md](./ISSUE357_GITHUB_BODY_FINAL.md) | 当前 Issue 正文；关联 Draft PR `c2875a5` | 产品 `927c5de`；公开证据基线 `7098b43` | OPEN；C1 主指标、实时 cadence、Attention/MoE 待导师裁决             |
| Task 11 PR #378  | [PR378_GITHUB_BODY_FINAL.md](./PR378_GITHUB_BODY_FINAL.md)       | head `c2875a5`                           | 产品 `927c5de`；公开证据基线 `7098b43` | OPEN、Draft；当前头 CI 8/8 成功；仍有未完成验收项                   |

## 本地新增证据

截至基线 `233e5f8`，新 native loss/grad 补验已判 `PASS_WITHIN_OFF_OFF_ENVELOPE`：测量差值 loss `0.05001947 / 0.04827869`（冻结限值 `0.2334780693`），grad norm `8.3840971 / 12.530714`（冻结限值 `57.43427467`）。该判定仅限同版两对 48 步数值比较，不更新 a48a23b 旧 loss/grad `UNSCORED`，不构成整体 C2 PASS。

结果、校准锁、测量锁、工具及测试所在的本地提交为 `86e35e2`、`1850beb`、`eaf3c63`、`233e5f8`。八臂只读审计最终版在本地 `e8d200a8d2853448618721952ae3f703d1054aac`，工具 SHA-256 `b8233b8cfd35a4e422db4933e1352ba030c7c3391d5823444d2198afb9e83af1`，37 项测试与八臂复算通过。自然告警报告、SVG 和加固后的 replay 工具固定于本地 `4e4e736878e5328e7c59f39d21fdceea1046a430`；复放工具 SHA-256 `efff2163496b5f60c3c43a347cd212bd1529b7b3007b36777521cbec92d7b16c`，新增 12 项测试通过，覆盖 job-log/raw-file 哈希、重复 JSON 键与 envelope 身份、raw-root symlink confinement。报告 SHA-256 `0cc0d3d1c7f57f5327055d9451883b74c9268be3cdf817c83d927799b01377f`，图 SHA-256 `de645d462b2868baf7aa27fdaccb77365f92dbd730299c91eca9110df537b1ca`。所有这些都是本地证据，尚未发布。参数记录 `116d527` 经 GitHub API 返回 404，明确为 local-only；非张量审查确认每对 47/48 叶一致，唯一差异位于含运行路径、TensorBoard 名称及 TransferQueue 运行态信息的 args 叶。

loss/grad 差值图为 `native_loss_envelope_20261001.svg`，数据取自 measurement verdict；参数图为 `evidence/gpu_campaign/task11_3090/c2_parameter/parameter_deltas.svg`。自然告警时序图及逐条数据表为本地审计源 `evidence/gpu_campaign/task11_3090/native_loss_927c5de/NATURAL_ALERT_REVIEW_20261001.svg` / `.md`。各图先保留本地源路径，获准发布后再替换成不可变 URL。

## 证据出处与核验说明

- C3 的输入包已公开于 `7098b43`；29 项直接对象/归档成员哈希匹配。独立复算过程在本机执行，输出与冻结 JSONL/TensorBoard 结果一致。正文应写“基于公开输入包的本地独立复算”，不写“公开复算平台已执行”。
- C3 原结果的阶段摘要写“三个阶段”，逐项 JSONL 实际有四个目标阶段标签；候选正文按原始条目写四个，不改冻结结果文件。
- C3 减速臂的 3 条非目标告警按预注册窗口代理规则归为误报，成因未证实。observer-only 两臂有 4,011 条 envelope，复放重现保存的 7 条确认告警；六条有保存恢复、M1/r2 一条快照时仍 active，原因未知，不判误报。
- 非终态尾窗离线复放另有 5 个候选，不能当作实时保存告警；`closed=false`、每臂两窗未关闭，M1 尚有 6 个 pending readouts、M2 有 1 个。现有快照计数为零不构成最终零丢弃证明。报告、图及加固脚本见本地提交 `4e4e736`；公开链接仍未生成。
- a48a23b 的旧 loss/grad 差值 `0.046285/0.030037` 和 grad `7.94949/5.50596` 属于参数实验旁证，因首个 ON 前未冻结容差而保持 `UNSCORED`。
- a48a23b overlap `NOT_PASS` 与 927c5de 独立预注册 overlap `PASS` 各自绑定对应协议，不能覆盖或合并。

## 发布前差异检查

本轮约束为仅本地提交，不 push、不写 GitHub。后续只有在该约束由有权者明确解除后，才可发布证据并同步远端正文；发布前必须完成：

1. 最终工具/复放门禁提交固定；Task 4 对应 `0481701` + evidence `fdf288d`，Task 11 对应 `927c5de` + 已公开基线 `7098b43`，本地新增 evidence 均标成未公开。
2. 远端重新下载已授权的证据包，核对文件 SHA 并在隔离目录独立复算；只有实际完成后才改称公开可复算。
3. 再读四个远端正文、CI 与 mentor/review 回复；有新增决策或远端代码头变化时先同步事实。
4. #378 保持 Draft；不要把 native 补验写成 C1、整体 C2 或 Task 11 PASS。#370 仍待 approval 与三项裁决。
5. 用正文源更新四项后回读比较；保留维护者意见，不通过新评论重复播报状态。

## 未闭合事项

- Task 4：维护者 review approval 与 artifact 归属、4×4090 验收规模、采样语义裁决。
- Task 11：C1 主指标与确认实验；rollout cadence 是否满足实时；Attention/MoE 范围；两 observer-only 运行尾窗没有终态关闭与最终丢弃 accounting；native 补验及参数原始大文件的可迁移/独立存储和公开复算。
