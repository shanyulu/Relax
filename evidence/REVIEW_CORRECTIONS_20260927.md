# Task 11 验收复核更正

本记录更正 `afd45fb04de9306b2e65f851ee2b7c7dbbe917b4` 的验收解释，不覆盖原始实验或旧分析文件。实验产品为 `a48a23ba5a39b3410a19e91d5f362154d97c9977`。

## 结论

| 项目 | 复核结果 |
| --- | --- |
| C1 | 旧产品六对 pilot 仍为 INCONCLUSIVE；不迁移为新产品开销证明 |
| C2 日志指标 | 两对测量臂 loss、grad、lr、token、更新数通过原检查 |
| C2 参数 | NOT_MEASURED。两对 checkpoint 树哈希不同，旧非确定分支漏掉参数比较；不得以 loss 包络替代 |
| C2 综合分析器 | 修复后 `C2_COMPARE_REVIEWED.json` 为 INCOMPLETE，0 指标违规、2 项参数证据缺失 |
| overlap | 原冻结 NOT_PASS 保留；不能已知 ON 结果后放宽原包络 |
| 同步 | 原计数只覆盖 cudaDeviceSynchronize，不支持“没有任何新增同步” |
| C3 定位 | 六条 straggler：rank 3 五条、rank 2 一条；不是六条均定位注入目标 |
| C3 延迟 | UNMEASURED。旧分位数是无事件关联的日志到文件增长间隔 |
| C3 末窗 | UNVERIFIED。最后一条 verdict 的类别不证明最后一个已接受窗口被正确关闭 |
| 平台 | worst_rank 混合 uncertain 与已确认告警；需要独立确认告警指标及平台回归 |

原始 checkpoint 已由旧 runner 删除，哈希无法恢复参数距离。新 runner 停止自动删除 checkpoint，但这不补全旧实验。OFF/OFF 的 15×48 个差值并非 720 个独立样本。

## 可复算输入与命令

本次补入 measurement 四臂的原始 `job.log`，不修改字节。此前仅 manifest 在库，干净克隆无法重算。

```bash
python evidence/tools/c2_lock.py compare \
  --lock evidence/gpu_campaign/c2-a48a23b/measurement/C2_MEASUREMENT_LOCK.json \
  --calibration-result evidence/gpu_campaign/c2-a48a23b/C2_CALIBRATION_RESULT.json \
  --campaign evidence/gpu_campaign/c2-a48a23b/measurement \
  --out /tmp/C2_COMPARE_REVIEWED.json
```

预期退出码 1、INCOMPLETE；输出路径必须尚不存在。新结论不是重跑 GPU 得到的 PASS。

`c3_summary_slow_reviewed.json` 保留旧时间差供审计，但不把它放进事件延迟字段。新增合成反例验证：任意 step 日志不能成为匹配事件，嵌套 GPU kernel 区间不能产生虚假空闲 gap。

## 仍须完成，不能归类为外部审批

1. 将产品确认告警修复提交到公开 PR 后，在最终产品版本验证平台归属；本地测试不能替代该验证。
2. 参数比较独立预注册：保留 checkpoint 或完整可复算参数快照，声明张量键/shape/dtype 检查、逐参数数值指标、校准与判定规则；先 OFF/OFF，再冻结 ON/OFF 测量。
3. overlap 使用独立校准会话与保留测量数据，锁定统计单位、效应边界、固定样本数和停止规则；不修改旧失败。
4. C3 用同一事件身份关联 interval、verdict 与平台可见时间；跨进程验证时钟可比性，单独检验尾窗口和非目标 rank 告警。
5. 原始 trace 目前仍需公开可下载归档并核对既有 SHA256；不能仅凭服务器存在就声称公开可复算。

C1 主指标、实时 cadence 与 attention/MoE 范围仍需明确。代码修复改变产品版本后，受影响验收须重新确认。
