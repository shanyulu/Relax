# 参数证据跨目录复算

## 用途与边界

产品为 `927c5de`。本工具只处理已有四个参数测量臂，不提交训练、不转换 checkpoint、不修改冻结协议或参数原件。

三个根目录必须真实存在、互不重叠，且保留原来的相对目录结构：

| 逻辑根目录                                      | CLI 参数         | 必需内容                                           |
| ----------------------------------------------- | ---------------- | -------------------------------------------------- |
| `/tmp/codex-task11-evidence`                    | `--repo-root`    | 完整 evidence Git 历史、冻结工具、执行锁、校准结果 |
| `/root/autodl-tmp/relax-work/task11-c2-927c5de` | `--product-root` | 干净的冻结产品 Git checkout，以及原 recipe         |
| `/root/autodl-tmp/task11-3090`                  | `--data-root`    | dataset、environment 指纹及四臂完整原件            |

不可只下载 inventory 或哈希台账。每臂仍须保留原 DCP、原始转换文件、sanitized payload、inventory、NumPy payload、manifest 和 job 日志。冻结锁中绑定的 recipe、dataset、environment、协议、runner、comparator、adapter 都必须在对应映射路径可读。

## 两种模式

从恢复后的 evidence 仓库执行；以下三个实际路径均为示例，需替换为恢复目录：

```bash
python3 /restore/evidence/evidence/tools/c2_parameter_replay_927c5de.py \
  --repo-root /restore/evidence \
  --product-root /restore/product \
  --data-root /restore/data \
  --metadata-only \
  --audit-out /restore/metadata_mapping.json
```

`METADATA_ONLY` 校验提交与工具哈希、产品 HEAD/源码指纹、锁及小型记录、四臂训练记录、身份、自哈希、路径约束和原件是否存在。它**不读取大文件作全量哈希，也不比较参数数值，不产生验收 PASS**。

完整复算去掉 `--metadata-only`，添加输出路径：

```bash
python3 /restore/evidence/evidence/tools/c2_parameter_replay_927c5de.py \
  --repo-root /restore/evidence \
  --product-root /restore/product \
  --data-root /restore/data \
  --out /restore/parameter_verdict.json \
  --audit-out /restore/full_mapping.json
```

输出及其父目录必须事先规划好；已有输出拒绝覆盖。`audit-out` 独立记录实际映射、replay 源码哈希和请求的验证模式，不替代验收结果。正式复算会重新读取并校验全部 DCP、转换产物及 tensor payload，需预留数十 GiB RAM 和足够时间；不要与训练或其他大文件哈希并发运行。

## 保留的校验链

- 完整执行锁及 Git 源文件提交校验；冻结产品 HEAD、干净状态、recipe、dataset、environment 和工具哈希。
- 四臂的身份、48 步日志、worker/driver 来源、退出状态与资源归还记录。
- 两个按 `P-M1`、`P-M2` 排序的 pair，OFF/ON 标签、measurement lock、校准提交和文件哈希、容差表绑定。
- 每份 inventory 的唯一张量键、形状/dtype、身份与自哈希；原 DCP → raw conversion → sanitized → inventory → NumPy 的完整 lineage。
- 数值复用已冻结 bounded 比较函数；不修改容差、浮点比较或 verdict 含义。

原 JSON 与其哈希保持不变。路径转换仅作用于隔离函数调用域；不修改 `pathlib.Path`、原模块 globals 或磁盘 manifest。未知根目录、父目录穿越、符号链接越界、重复/嵌套映射均拒绝。

迁移后的 verdict 保留冻结的逻辑 `calibration_path`，不会写入恢复机器路径。正常完整输入下，其结果 JSON 应与同路径结果逐字节相同；映射记录放在独立文件中。

## 当前验证强度

已以小型 CPU fixture 验证迁移前后的完整 lineage 与参数比较，结果字节一致；另对真实四臂完成 metadata-only 预检。**尚未在另一目录全量复算真实大参数原件**，不得将 fixture 等价性或路径预检写成跨机大原件验收闭环。

大原件目前仅本地保留，公开下载入口尚未闭环。未拿到全部原件时只能审核小型记录，不能声明第三方完整复算成功。

退出码：`0` 为 metadata-only 预检完成或数值 PASS（必须结合模式和输出判断）；`1` 为数值 NOT_PASS/INCOMPLETE；`2` 为输入/恢复环境拒绝。输入异常会输出 `REPLAY REFUSED`，不伪造冻结 verdict。
