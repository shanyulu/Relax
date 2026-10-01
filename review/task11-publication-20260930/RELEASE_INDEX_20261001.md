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

结果、校准锁、测量锁、工具及测试所在的本地提交为 `86e35e2`、`1850beb`、`eaf3c63`、`233e5f8`。新增八臂只读工具审计首版与 32 项测试在本地提交 `ce39ee1`；复审又发现重复 JSON 键、raw-root symlink 逃逸和输出拒绝覆盖门禁待补，最终审计版本待主线完成后再固定。这些 SHA 目前只定位本地证据，正文没有将其伪装成远端链接。参数结果绑定 `116d527`；非张量审查确认每对 47/48 叶一致，唯一差异位于包含运行路径、TensorBoard 名称及 TransferQueue 运行态信息的 args 叶。

## 证据出处与核验说明

- C3 的输入包已公开于 `7098b43`；29 项直接对象/归档成员哈希匹配。独立复算过程在本机执行，输出与冻结 JSONL/TensorBoard 结果一致。正文应写“基于公开输入包的本地独立复算”，不写“公开复算平台已执行”。
- C3 原结果的阶段摘要写“三个阶段”，逐项 JSONL 实际有四个目标阶段标签；候选正文按原始条目写四个，不改冻结结果文件。
- 减速臂的 3 条非目标告警按预注册窗口代理规则归类为 false positive，原因未证明。额外 observer-only 自然告警仍待单独复核；不提前归因。
- 最新自然告警核查：两个 ON 运行可重算出 7 条 runtime-confirmed 告警，原因未定；尾窗复放出的 5 条只是候选，因为 runtime status 非终态（`closed=false`、2 个 open windows），M1/M2 collector status 早于 manifest 完成。详细审计报告和 commit hash 待主线补入，不将这 5 条描述为已发布告警，也不作最终零丢弃证明。
- a48a23b 的旧 loss/grad 差值 `0.046285/0.030037` 和 grad `7.94949/5.50596` 属于参数实验旁证，因首个 ON 前未冻结容差而保持 `UNSCORED`。
- a48a23b overlap `NOT_PASS` 与 927c5de 独立预注册 overlap `PASS` 各自绑定对应协议，不能覆盖或合并。

## 发布前差异检查

1. 先把新 evidence ref 和所需的小证据包实际推至已授权的个人 fork；更新正文中“本地候选”状态与链接，并完成下载后哈希核对及隔离复算。
2. 核对 `#351` / `#370` 仍是产品 `0481701`、Task 4 证据 `fdf288d`；核对 `#357` / `#378` 仍是产品 `927c5de`，公开基线仍为 `7098b43`。若远端 head 或导师回复变化，以远端新事实重写表格再发布。
3. 保持 #378 Draft；不把独立 native 补验写成 C1、整体 C2 或 Task 11 PASS。#370 仅在 approval 和三项裁决完成后合入。
4. 使用这些正文源分别更新 Issue/PR 正文；写入前回读当前 body，保留新评论和维护者意见。写入后再回读并与最终正文比对。

## 未闭合事项

- Task 4：维护者 review approval 与 artifact 归属、4×4090 验收规模、采样语义裁决。
- Task 11：C1 主指标与确认实验；rollout cadence 是否满足实时；Attention/MoE 范围；observer-only 自然告警逐条审查；新补验和参数原始大文件的可迁移/独立存储及公开复算。
