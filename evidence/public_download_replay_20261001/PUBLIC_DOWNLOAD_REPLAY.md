# Task 11 公开下载复算记录（2026-10-01）

产品：`927c5de2f5a8f307cad0c87f2c7eb2b78262334d`。本次从 GitHub Release 重新下载输入，在新的本地目录执行 CPU 复算；未运行训练，未改产品、冻结比较器、容差或历史 verdict。

输入固定于 [evidence 1c23f03](https://github.com/shanyulu/Relax/tree/1c23f03d3553e26194c09f90d2ce0e85f7895c00/evidence)，下载位于 [Release](https://github.com/shanyulu/Relax/releases/tag/task11-evidence-20261001-1c23f03)。以下结果已实际执行。

| 检查                  | 结果                                                                                      |
| --------------------- | ----------------------------------------------------------------------------------------- |
| Native loss/grad 小包 | 917,446 字节；下载 SHA-256 与发布前原包一致；96 项 MANIFEST 全匹配                        |
| Native 八臂重算       | `PASS_WITHIN_OFF_OFF_ENVELOPE`；精确映射旧 Ray 源码路径到干净产品 checkout 并重算源码指纹 |
| 自然告警重放          | M1 145/145、M2 139/139 保存 verdict payload 匹配；输出与冻结 JSON 逐字节一致              |
| 下载包内工具测试      | 三套测试合计 71 passed                                                                    |
| 3090 trace 下载       | 八包、526,027,308 字节；全部 archive SHA-256 与冻结台账一致                               |
| Trace 身份            | 八份 manifest 匹配预注册 config；32 件 trace 完整集合及各自哈希由冻结分析器校验           |
| Overlap 重算          | freeze/compare 均 PASS；两份生成结果与冻结 JSON 经 cmp 逐字节一致                         |

## 固定哈希

- 小包：`af1aff9db1b8c4f251b23b7e56d25d9b487fb43e1ee15bcc5259695b5e1f72c2`。
- 下载后 native 审计文本：`4e4d7270543c72dc2219f8237e9b9b6f37691f9438cab31c7a9655c850cd2cf3`；文本含本次解包路径，原字节编码在同目录 `PUBLIC_DOWNLOAD_NATIVE_AUDIT.json` 的 `content_base64`，解码可核对该哈希。
- 告警复放输出：`b094a71c72b59848796da1c1cf25a0a640ec6320d6680df69af566ab71aca942`；与原 `native_loss_927c5de/ALERT_REPLAY_20261001.json` 相同。
- Overlap calibration：`7eca09527aa726e82e07daed3d9ad2081deb315b6857fd6f06799eee75107f0e`。
- Overlap measurement：`821786baa46edbef6d17eb26c42ec21b164574a000dd02ff420ffa3f57b1d614`。
- Trace 分析器：`7654e337e46b0be6a7e92506b61b9a549813e3988e9fba21978c5fb64df31e0d`。

机器收据为同目录 `PUBLIC_DOWNLOAD_RECEIPT.json`。发布前的包 README、归档说明及工具 `raw_artifacts_are_local_only` 字段记录了原归档状态；实际公开性由本次 Release 下载、哈希与复算记录证明。原归档字节未被重写。

## 复算入口

Native 按 [包内说明](../gpu_campaign/task11_3090/native_loss_927c5de/BUNDLE_README_20261001.md)执行，源码使用干净产品 checkout。对包内三套工具测试执行：

```bash
PYTHONPATH=tools python -m pytest -q -p no:cacheprovider \
  tools/test_native_loss_campaign_927c5de.py \
  tools/test_native_loss_gate_audit_927c5de.py \
  tools/test_replay_native_loss_alerts_20261001.py
```

Trace 在 evidence `1c23f03` 的 checkout 中执行下列命令。所有下载、解压及新输出进入独立临时目录；原 verdict 保持原字节。

```bash
audit=$(mktemp -d /tmp/task11-public-trace.XXXXXX)
root=evidence/gpu_campaign/task11_3090/trace_overlap
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  gh release download task11-evidence-20261001-1c23f03 \
  -R shanyulu/Relax --pattern 'O-*.tar.gz' --dir "$audit/archives"
jq -r --arg base "$audit/archives/" \
  '.archives[] | "\(.sha256)  \($base)\(.path|split("/")|last)"' \
  "$root/PUBLIC_TRACE_LEDGER_20260930.json" | sha256sum -c -
mkdir -p "$audit/calibration" "$audit/measurement"
for arm in O-C1-off O-C2-off O-C3-off O-C4-off; do
  tar -xzf "$audit/archives/$arm.tar.gz" -C "$audit/calibration"
done
for arm in O-M1-off O-M1-on O-M2-on O-M2-off; do
  tar -xzf "$audit/archives/$arm.tar.gz" -C "$audit/measurement"
done
for phase in calibration measurement; do
  case "$phase" in
    calibration) config="$root/O_FREEZE_CONFIG.json" ;;
    measurement) config="$root/O_MEASUREMENT_CONFIG.json" ;;
  esac
  jq -r --arg raw "$audit/$phase" \
    '.arm_manifest_sha256 | to_entries[] | "\(.value)  \($raw)/\(.key)/manifest.json"' \
    "$config" | sha256sum -c -
done
python evidence/tools/trace_verdict_927c5de.py freeze \
  --config "$root/O_FREEZE_CONFIG.json" --raw-root "$audit/calibration" \
  --out "$audit/O_CALIBRATION_RESULT.json"
python evidence/tools/trace_verdict_927c5de.py compare \
  --config "$root/O_MEASUREMENT_CONFIG.json" --raw-root "$audit/measurement" \
  --calibration-result "$audit/O_CALIBRATION_RESULT.json" \
  --out "$audit/O_MEASUREMENT_RESULT.json"
cmp "$audit/O_CALIBRATION_RESULT.json" "$root/O_CALIBRATION_RESULT.json"
cmp "$audit/O_MEASUREMENT_RESULT.json" "$root/O_MEASUREMENT_RESULT.json"
```

## 未闭合边界

- 此处证明公开下载的观察数据能重现冻结判定，未重跑训练，也未恢复完整训练环境。
- 约 258 GiB 参数原件未包含在包中；本地完整参数复算已通过，第三方完整复算和独立备份继续待办。
- 两条 observer-only 运行的终态关窗及 pending readout/drop accounting 未证明；未解释的自然告警保留未知原因。
- C1、整体 C2 覆盖、实时节奏及 Attention/MoE 范围仍按各自裁决处理。

新材料定向 pre-commit 通过。全仓 pre-commit 在隔离副本执行：EOF、Ruff、mdformat、clang-format、docformatter 等对冻结历史文件产生修改并失败；这些修改未迁回，不能宣称该 evidence 分支全仓格式检查通过。两个产品 PR 的当前头 CI 8/8 仍按其真实 SHA 记录。
