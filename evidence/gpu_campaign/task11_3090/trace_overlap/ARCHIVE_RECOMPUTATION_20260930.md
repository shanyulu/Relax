# 3090 overlap 原件归档与复算

产品：`927c5de2f5a8f307cad0c87f2c7eb2b78262334d`。这是一组新机器的独立实验；
不覆盖旧 overlap 的 NOT_PASS，不是 C1 性能确认实验。

## 归档规则

八个 `archives/<arm>.tar.gz` 分别包含一臂原 manifest 和四 rank trace。
成员路径保留 `<arm>/train_trace/<original-name>`，成员字节保持不变。
`PUBLIC_TRACE_LEDGER_20260930.json` 同时固定压缩包、40 个成员及重算产物的 SHA-256。
每个原 manifest、32 个 trace 都必须匹配预注册配置中的
`arm_manifest_sha256` / `raw_trace_hashes`，不是与事后新生成的清单自洽即算通过。

`TRACE_SCAN_REPORT_20260930.json` 使用仓库 `.gitleaks.toml` 与缓存的 gitleaks 8.30.1，
对 32 个原 gzip 完整解压后的 UTF-8 内容逐个 stdin 扫描；不是只扫 gzip 包头。
只有全部 PASS 才生成归档。没有改原件、调整规则或添加路径豁免。
另对归档内八份 manifest 执行同规则独立扫描，8/8 PASS、零发现，
见 `MANIFEST_SCAN_REPORT_20260930.json`；归档的 40 个内容成员均经过检查。

## 从归档重算

在 evidence 仓库根目录，使用已有 Python 依赖：

```bash
root=evidence/gpu_campaign/task11_3090/trace_overlap
audit=$(mktemp -d /tmp/task11-overlap-recompute.XXXXXX)
mkdir -p "$audit/calibration" "$audit/measurement"
for arm in O-C1-off O-C2-off O-C3-off O-C4-off; do
  tar -xzf "$root/archives/$arm.tar.gz" -C "$audit/calibration"
done
for arm in O-M1-off O-M1-on O-M2-on O-M2-off; do
  tar -xzf "$root/archives/$arm.tar.gz" -C "$audit/measurement"
done
jq -r '.archives[] | "\(.sha256)  evidence/gpu_campaign/task11_3090/trace_overlap/\(.path)"' \
  "$root/PUBLIC_TRACE_LEDGER_20260930.json" | sha256sum -c -
python3 evidence/tools/trace_verdict_927c5de.py freeze \
  --config "$root/O_FREEZE_CONFIG.json" --raw-root "$audit/calibration" \
  --out "$audit/O_CALIBRATION_RESULT.json"
python3 evidence/tools/trace_verdict_927c5de.py compare \
  --config "$root/O_MEASUREMENT_CONFIG.json" --raw-root "$audit/measurement" \
  --calibration-result "$audit/O_CALIBRATION_RESULT.json" \
  --out "$audit/O_MEASUREMENT_RESULT.json"
cmp "$audit/O_CALIBRATION_RESULT.json" "$root/O_CALIBRATION_RESULT.json"
cmp "$audit/O_MEASUREMENT_RESULT.json" "$root/O_MEASUREMENT_RESULT.json"
```

冻结分析器自动校验完整 trace 集合与原 SHA-256。
生成脚本 `trace_archive_verify.py` 另核验归档 manifest 与冻结配置的哈希，
逐成员解压校验，再运行上述两次分析；其生成模式是 write-once，不能覆盖已生成包。

## 判定边界

本次实际检查：八包共 `526027308` 字节（约 501.66 MiB），40 个成员哈希全匹配；
新解压目录 `/tmp/task11-overlap-archive-audit-l2dn_h0s` 中生成的
calibration 与 measurement 结果均 PASS，且与已冻结 JSON 逐字节一致。
台账 SHA-256：`566289d433792e95214cd55d93317e385d20e9d0e4cba52f39081b4541838568`。

冻结允许下降为 `0.0014555235430011582`；两对 ON−OFF 分别为
`+0.0005629700971351848` 和 `−0.00022059325083634285`。
这只检验该配方、机器和冻结包络下的 overlap 门槛。
`cudaDeviceSynchronize` 计数均为 68，只代表该 API，不代表检测了所有同步。
不能由此声明“零影响”“没有新增任何全局同步”或“开销小于 0.5%”。

正式归档检查以 ledger 的 `recomputation` 与扫描报告为准；未提交、未 push 的本地包
不能称为已可从公开链接下载。

每包约 66 MiB，超过现有 `check-added-large-files` 的 500 KiB 门禁。
当前没有 LFS 配置或已授权外部存储地址；因此归档先保留本地，
小型台账与说明可提交，但公开下载交付仍未闭环。不得跳过 hook、
改门禁或把千余个碎片塞入 Git 来伪装完成。
