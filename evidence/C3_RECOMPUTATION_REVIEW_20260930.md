# C3 公开输入独立复算（2026-09-30）

产品固定为 `927c5de2f5a8f307cad0c87f2c7eb2b78262334d`。按
`gpu_campaign/c2p-927c5de/c3-v2/C3_PUBLIC_RECOMPUTE.md` 的现有步骤，
从公开包复制、解压并重新分析；没有运行 GPU、改产品或调整分类规则。

## 核验结果

| 检查             | 结果                                                                 |
| ---------------- | -------------------------------------------------------------------- |
| 公开台账         | 11 个直接对象、18 个归档成员，共 29 项 SHA-256 全匹配                |
| 冻结入口         | lock、原结果、两份平台结果、分析器和平台提取器，共六项哈希均匹配台账 |
| JSONL 分类重算   | 与冻结 `C3_RESULT.json` 一致                                         |
| TensorBoard 重算 | 健康与减速两臂均与冻结结果一致                                       |
| 允许不同的字段   | 两个已脱敏 job log 的哈希；平台结果的绝对 `arm` 路径                 |
| 其他字段         | 无差异；未增加豁免                                                   |

两份原 job log 哈希分别匹配对应 `TRANSFORM.json.original_sha256`；
重算结果中的公开日志哈希匹配 `public_sha256`。不是简单删除哈希字段后跳过身份验证。
原件、冻结结果及原分类均保持不变。

## 实际观测与勘误

- 健康臂：37 条 uncertain，0 条 straggler。该观察不证明总体误报率为零。
- 减速臂：rank 3 有 4 条目标检测，最大 deviation 为 `6.868772661248295`；
  阶段标签为 `backward-compute`、`all-grads-sync`、`forward-compute`、`forward-backward`。
  原 `C3_RESULT.md` 的 “across three stages” 应在后续正文改为“四个阶段标签”，
  不能修改冻结 JSON 或写成旧版本的 6 条检测。
- 减速臂另有 3 条非目标告警。按冻结协议均分类为 false_positive：rank 1
  `backward-compute`，rank 2 `all-grads-sync`、`forward-compute`；三者均未与目标慢窗口重叠。
  不将它们改称“注入连带效应”。
- 平台：健康臂 15 个序列、active 步数 0；减速臂 17 个序列、active 步数 32、最大 active 7。
- 阶段级 JSONL 定位与 rollout 级平台确认已复算；逐事件平台延迟仍为 UNMEASURED。
  是否满足官方“实时”验收仍待维护者裁决。

本次临时复算目录：`/tmp/task11-c3-public-audit-ds9w9daa`。
这只证明公开原件能重现已记录的观察，不是 C3 全部官方验收通过。
