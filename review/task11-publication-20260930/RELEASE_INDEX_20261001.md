# 四链接正文与证据发布索引（2026-10-01）

| 项目             | 正文源                                        | 产品 / PR 头          | 当前结论                                          |
| ---------------- | --------------------------------------------- | --------------------- | ------------------------------------------------- |
| Task 4 RFC #351  | [Issue 正文](./ISSUE351_GITHUB_BODY_FINAL.md) | `0481701` / `da4acbb` | 范围与证据边界保留；三项裁决待维护者答复          |
| Task 4 PR #370   | [PR 正文](./PR370_GITHUB_BODY_FINAL.md)       | 同上；当前头 CI 8/8   | 等当前头 approval，不新增 GPU 实验或产品变更      |
| Task 11 RFC #357 | [Issue 正文](./ISSUE357_GITHUB_BODY_FINAL.md) | `927c5de` / `c2875a5` | 分项证据更新；C1、实时节奏与 Attention/MoE 待裁决 |
| Task 11 PR #378  | [PR 正文](./PR378_GITHUB_BODY_FINAL.md)       | 同上；当前头 CI 8/8   | 保持 Draft，整体验收未完成                        |

## 本次交付

- 证据数据与工具固定于 [1c23f03](https://github.com/shanyulu/Relax/tree/1c23f03d3553e26194c09f90d2ce0e85f7895c00/evidence)；图注修订固定于 [d67c189](https://github.com/shanyulu/Relax/commit/d67c189015efa237946935f75bc19d5596b09686)。
- [公开下载复算记录](https://github.com/shanyulu/Relax/blob/41f2521cfef7dd3dc2bbd8e10dbb3f8a8dccf5de/evidence/public_download_replay_20261001/PUBLIC_DOWNLOAD_REPLAY.md)固定于 `41f2521`，包含实际下载与机器收据。
- [Release](https://github.com/shanyulu/Relax/releases/tag/task11-evidence-20261001-1c23f03)有九个输入附件：native 小包 917,446 字节；八个 3090 trace 包合计 526,027,308 字节。
- native 小包 96 项清单匹配；八臂复算为 `PASS_WITHIN_OFF_OFF_ENVELOPE`；保存告警 payload 匹配 145/145、139/139，输出与冻结 JSON 逐字节一致。下载包内三套工具测试为 71 passed。
- 3090 的八份 manifest 与32件 trace 匹配冻结 config；calibration/measurement 都 PASS，生成文件与冻结结果逐字节一致。
- 本地完整参数复算两对各 182/182 entries 通过。其中13个是非空浮点 storage 组，169个是零元素 TE 占位；非张量叶每对47/48一致，不能据此声明完整恢复状态等价。
- 参数 P-M 旁证 loss `0.046285/0.030037`、grad `7.94949/5.50596` 属于 `927c5de`，保持 `UNSCORED`；新 L-M 补验独立判定。旧 `a48a23b` overlap `NOT_PASS` 保留。
- 新图、表和正文使用同一冻结数据；修正将 GitHub 目录当图片的问题，并将新增图替换为不可变 raw 图片地址。

## 检查与发布范围

四份中文正文使用上表源文件更新；只发布个人 fork 的 evidence 分支与 Release，两个产品 PR 分支保持原头。维护者评论、评审记录、历史 verdict 和完整原件保留。

新材料定向 pre-commit 通过，gitleaks 扫描通过。全仓检查在隔离副本执行，历史证据被 EOF、Ruff、mdformat、clang-format 和 docformatter 修改而失败；修改未迁回。该 evidence 分支不宣称全仓格式检查通过，两个产品 PR 的当前 CI 按其真实 SHA 记录。

## 仍待闭合

- Task 4：当前头 approval；artifact 归属、4×4090 验收规模、内容派生 seed 三项裁决。
- Task 11：C1 主指标与正式确认实验；实时节奏及 Attention/MoE 范围；整体 C2 覆盖接受。
- 约258 GiB参数原件仍仅本地：独立存储、完整第三方恢复复算未完成。
- 两条 observer-only 运行缺终态关窗/readout/drop accounting；七条保存告警中未知原因保留未知，五个离线尾窗候选不写成已保存告警。
