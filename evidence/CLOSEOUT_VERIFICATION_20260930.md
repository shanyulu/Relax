# 2026-09-30 本地收口验证

本次不修改产品、不启动 GPU、不 push、不编辑 GitHub。冻结参数正式结果仍为 `116d527`，产品仍为 `927c5de`。

## 已验证

- 参数工具链及新增 audit／replay／SVG 测试：115 passed。新增三个测试文件合计 43 项。
- replay 对真实四臂完成 metadata-only 检查；记录绑定格式化后的真实源码哈希。没有重复运行大参数数值比较，不宣称真实跨目录完整恢复成功。
- overlap 八归档共 526,027,308 字节；32 trace 与八 manifest 匹配冻结哈希、扫描无发现；从新解压输入重算两个结果，与冻结 JSON 逐字节一致。
- C3 原始公开派生对象重算：29 对象、六入口哈希核验；分类及平台结果一致，只有原脱敏日志哈希和绝对 arm 路径的预先记录差异。
- 新文件提交范围 pre-commit 全通过；大包和原始 train_trace 未 stage。

## 全仓检查不能报绿

在隔离副本 `/tmp/codex-task11-precommit.ZZLmCA` 运行 `pre-commit run --all-files --show-diff-on-failure`，包含本次新文件及中文正文候选。
既有 Ruff 错误仍为 `manifest.py` 的 C416、`run_abba_sessions.py` 的 F841、`straggler_startup_decompose.py` 的两处 F841；既有 `LATENCY_REPORT.md` 触发 mdformat 渲染等价失败。

记录：`/tmp/task11-full-check-including-new-20260930.log`，SHA256 `04bb71b4e74d4daa41cdbe585a62750f17c76dd81fc1cde9d6e5cd7bd16a21c7`。
历史自动格式化只留在隔离副本，未迁回冻结 evidence；本次没有绕过任何提交 hook。产品 PR 的 CI 与证据分支全仓检查是不同对象，不混用绿灯。

## 未关闭

本轮 loss／grad 为 UNSCORED；完整 optimizer 非张量状态未比较；C1 主指标与确认实验、C3 cadence、attention/MoE 范围待决定。新大归档与 checkpoint 仅本地保留，公开下载和真实跨位置完整恢复尚未闭环。

这些限制已同步到两份本地中文正文候选。旧版本的 PASS／NOT_PASS 保留原版本和门槛；没有通过事后放宽容差收口。
