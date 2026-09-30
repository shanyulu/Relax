# 3090 参数校准执行记录

产品：`927c5de`。四个 OFF 臂均完成 48 步；原始 checkpoint、转换产物、参数 payload 和日志保留在数据盘。

- 校准结果为 `FROZEN_OFF_ONLY`，不是参数测量 PASS。
- 固定对照为 C1/C2、C3/C4；13 个浮点张量的容差按 `2 × max(两次最大绝对差)` 冻结。169 个非浮点空占位张量仍须精确比较。
- 完成结果由 `f8ae6a1` 的 streaming executor 产生；成功退出码为 0。采样 RSS 峰值 62.34 GiB，cgroup 峰值 65.18 GiB，容器上限 360 GiB。
- 此前 SIGKILL 和 ENOENT 的现象保留在日志；根因没有得到独立证明，不将其归因为已确认的平台或文件系统缺陷。
- 新 bounded executor 复用原校准 builder，拒绝重复张量名；小型有效输入上的结果及自哈希与原工具一致。真实四臂清单均有 182 个唯一键。
- 原件尚未公开归档：当前可在本机复算，不声称仅凭公开仓库即可复算全部参数。
- 原始环境指纹不修改。正式测量如使用新 Ray session，另记补充 session provenance，不伪装成原 session 延续。

测量前须提交本结果、measurement lock 和执行工具锁。执行顺序为 M1-off、M1-on、M2-on、M2-off；四臂结束后才进行转换及比较。
