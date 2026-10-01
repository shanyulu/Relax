# 四份 Issue/PR 正文发布索引（2026-10-01）

这组文件是本地中文正文候选；本轮没有改动 GitHub。工作从本地提交 `233e5f8` 的隔离副本开始，Task 4 产品、证据与 PR 内容未改。四份正文须等证据发布后再替换为不可变公开链接；本地路径或 SHA 不能冒充可访问链接。

| GitHub 项目      | 正文源文件                                                       | 远端基线                                 | 产品 / 证据基线                        | 当前远端状态                                                        |
| ---------------- | ---------------------------------------------------------------- | ---------------------------------------- | -------------------------------------- | ------------------------------------------------------------------- |
| Task 4 RFC #351  | [ISSUE351_GITHUB_BODY_FINAL.md](./ISSUE351_GITHUB_BODY_FINAL.md) | 当前 Issue 正文；关联 PR `da4acbb`       | 产品 `0481701`；证据 `fdf288d`         | OPEN；artifact、验收规模、采样语义待维护者裁决                      |
| Task 4 PR #370   | [PR370_GITHUB_BODY_FINAL.md](./PR370_GITHUB_BODY_FINAL.md)       | head `da4acbb`                           | 产品 `0481701`；证据 `fdf288d`         | OPEN、非 Draft、mergeable；8 项必需 CI 成功；review approval 未取得 |
| Task 11 RFC #357 | [ISSUE357_GITHUB_BODY_FINAL.md](./ISSUE357_GITHUB_BODY_FINAL.md) | 当前 Issue 正文；关联 Draft PR `c2875a5` | 产品 `927c5de`；公开证据基线 `7098b43` | OPEN；C1 主指标、实时 cadence、Attention/MoE 待导师裁决             |
| Task 11 PR #378  | [PR378_GITHUB_BODY_FINAL.md](./PR378_GITHUB_BODY_FINAL.md)       | head `c2875a5`                           | 产品 `927c5de`；公开证据基线 `7098b43` | OPEN、Draft；当前头 CI 8/8 成功；仍有未完成验收项                   |

## 本地新增证据

新增本地证据的结论边界如下；三类结果互不替代，也不构成整体 C2 PASS。

| 证据                        | 当前判定                                                                                                                                                                                                               | 可复核材料                                                                                                                                                                                                                      |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Native loss/grad（927c5de） | `PASS_WITHIN_OFF_OFF_ENVELOPE`。48 步/臂；两对 loss 最大差 `0.05001947 / 0.04827869`，冻结限值 `0.2334780693`；grad norm `8.3840971 / 12.530714`，限值 `57.43427467`。旧 a48a23b 的 `UNSCORED` 不回溯改写。            | 审计报告 `TOOL_GATE_AUDIT_SOURCE_REMAP_20261001.md` SHA-256 `a32d899367ea13da2ca90f6d5bfd6ef2effccf2cc2caab4dd707459b4f26141d`；工具 SHA-256 `8f47444ea1ed3501f90358990fd5700df13016a718c5f781182879d1770ea43f`。               |
| Observer-only 告警复放      | M1 `145/145`、M2 `139/139` saved-verdict payload 完整匹配；仍有未闭合尾窗和 pending readouts，不能推断终态零丢弃或告警根因。                                                                                           | `ALERT_REPLAY_20261001.json` SHA-256 `b094a71c72b59848796da1c1cf25a0a640ec6320d6680df69af566ab71aca942`；工具 SHA-256 `77fdda54c7c6c42d15708bf5d89d3d8bdaf84d86d59fe799a22bed8fa7735471`。                                      |
| 参数复算                    | 每对 `182/182` entries 通过、零 violations、零缺失容差；非张量审查每对 `47/48` 一致，单一差异在运行态 `args`，不代表完整可恢复状态等价。                                                                               | 本地 commit `5173209`；verdict SHA-256 `73848f645b8043e7b37026882c8f7527a46807440918f1532b10c20e214a0f32`；mapping audit SHA-256 `c04c8a6ef4cdcc77f2a7e7e6a6729921a1a3b91297122e30e509f82546d67bc7`。258 GiB 参数原件仍仅本地。 |
| 可迁移小证据包              | 96 项清单全匹配；最终 archive 解压后 native-loss 判定通过，告警 payload 再匹配 `145/145`、`139/139`。显式映射 manifest 中记录的 Ray 源码路径，在干净产品 checkout 重算源码指纹，不依赖原 Ray working-directory cache。 | `NATIVE_LOSS_REPLAY_BUNDLE_20261001.tar.gz`：917,446 bytes，SHA-256 `af1aff9db1b8c4f251b23b7e56d25d9b487fb43e1ee15bcc5259695b5e1f72c2`。包不含模型、训练环境或 258 GiB checkpoint；仍在同一存储、未公开，不是独立备份。         |
| 工具与安全检查              | 三套测试合计 `71 passed`（native auditor 34、原 campaign 9、alert replay 28）。Gitleaks 8.30.1 扫描解包文件 6,284,963 bytes，零发现。                                                                                  | 扫描记录 `BUNDLE_SECURITY_SCAN_20261001.md`；空 JSON 报告 SHA-256 `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570`。                                                                                          |

loss/grad 差值图为 `native_loss_envelope_20261001.svg`，数据取自 measurement verdict；参数图为 `evidence/gpu_campaign/task11_3090/c2_parameter/parameter_deltas.svg`。自然告警时序图及逐条数据表为本地审计源 `evidence/gpu_campaign/task11_3090/native_loss_927c5de/NATURAL_ALERT_REVIEW_20261001.svg` / `.md`。各图先保留本地源路径，获准发布后再替换成不可变 URL。

## 证据出处与核验说明

- C3 的输入包已公开于 `7098b43`；29 项直接对象/归档成员哈希匹配。独立复算过程在本机执行，输出与冻结 JSONL/TensorBoard 结果一致。正文应写“基于公开输入包的本地独立复算”，不写“公开复算平台已执行”。
- C3 原结果的阶段摘要写“三个阶段”，逐项 JSONL 实际有四个目标阶段标签；候选正文按原始条目写四个，不改冻结结果文件。
- C3 减速臂的 3 条非目标告警按预注册窗口代理规则归为误报，成因未证实。observer-only 两臂有 4,011 条 envelope，复放重现保存的 7 条确认告警；六条有保存恢复、M1/r2 一条快照时仍 active，原因未知，不判误报。
- 非终态尾窗离线复放另有 5 个候选，不能当作实时保存告警；`closed=false`、每臂两窗未关闭，M1 尚有 6 个 pending readouts、M2 有 1 个。现有快照计数为零不构成最终零丢弃证明。报告、图及加固脚本见主线可达提交 `8b7006d`；公开链接仍未生成。
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
- Task 11：C1 主指标与确认实验；rollout cadence 是否满足实时；Attention/MoE 范围；两 observer-only 运行尾窗没有终态关闭与最终丢弃 accounting；native 小包虽已本地跨 Ray-cache 复算，仍未异盘或公开下载验证；258 GiB 参数原件仍需确定安全、可恢复的独立存储路径。
