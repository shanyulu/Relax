# 参数覆盖与原生训练旁证审查

产品：`927c5de2f5a8f307cad0c87f2c7eb2b78262334d`。参数正式结果来自本地提交 `116d527`。本审查不改冻结比较器、不重跑训练、不重复比较大参数。

## 覆盖结论

四个测量臂的 DCP `.metadata`、adapter 记录与 inventory 对照一致。检查了 tensor key、shape、dtype、chunk 边界、chunk 不相交及体积覆盖；只读取小型 metadata 和清单，未加载完整 checkpoint。

| 对象                   |                  每臂覆盖 | 意义                                                             |
| ---------------------- | ------------------------: | ---------------------------------------------------------------- |
| BF16 模型 storage      |   10 组，596,049,920 元素 | embedding、28 层堆叠的 attention/MLP/norm、final norm            |
| FP32 optimizer storage | 3 组，各 596,049,920 元素 | master parameter、`exp_avg`、`exp_avg_sq`；总 1,788,149,760 元素 |
| TE 空占位              |        169 个 uint8 `[0]` | 源于 extra-state byte 容器；零元素，不增加参数覆盖量             |
| 其余 byte 容器         | 4 个根、48 个非 tensor 叶 | adapter 显式排除并记录；不参与参数门禁                           |

因此“182/182 通过”指 **13 个有内容的浮点组与 169 个空占位项**，不是 182 个模型参数组，更不是 182 个独立样本。实验单位仍为两对 OFF/ON。

本审查证明元数据覆盖与已保留的转换记录一致，**不是再次独立执行 DCP 转换的证明**。未比较的非 tensor 叶包括 optimizer param-group 的 step、betas、eps、weight decay，scheduler 状态及 common args。不可由本次结果推导“完整 optimizer state 或可恢复训练状态逐项等价”。DCP byte 容器的具体语义只采用 adapter 已记录的叶清单，未重新反序列化。

## loss／grad 门禁缺口

`C2_PARAMETER_PROTOCOL_927C5DE.md`（最后变更 `c2723c4`）的 §1 明确继承 `C2_PROTOCOL_A48A23B.md`（`1346f20`）的 secondary checks。后者要求 loss／grad band **先从同版 OFF/OFF 冻结并提交，再运行 ON**，而非训练结束后计算容差。

本次 `P_CALIBRATION_RESULT.json`（`7237e1c`）、measurement lock（`4c9d9df`）与 execution lock（`4c74209`）仅冻结 per-tensor 参数容差；没有首个 ON 前提交的同版 loss／grad band。旧 `a48a23b` band 不能移植到本次 `927c5de`。因此两项为 **UNSCORED**，不能把有限数值、均值降低或参数 PASS 当作 loss／grad 门禁 PASS。

| 旁证                               |          P-M1 |          P-M2 | 判定               |
| ---------------------------------- | ------------: | ------------: | ------------------ |
| OFF／ON 更新数                     |        48／48 |        48／48 | 一致               |
| step ID、token、learning-rate 序列 |          一致 |          一致 | 一致               |
| 数值语境 NaN／Inf                  |             0 |             0 | 原生提取有效       |
| loss 最大逐步绝对差                |  0.0462852120 |  0.0300371647 | UNSCORED           |
| loss 平均 ON−OFF                   | −0.0060284324 | −0.0041741940 | 描述值，非收益证明 |
| grad norm 最大逐步绝对差           |  7.9494915009 |  5.5059623718 | UNSCORED           |
| grad norm 平均 ON−OFF              | −0.2070402503 | −0.4227267802 | 描述值，非因果证明 |

现有数据不能补造“提前冻结”。可接受处置只有：维护者明确接受既有参数与原生旁证作为替代，或另立独立协议、先冻结新 OFF 校准再运行新 ON；不得覆盖旧结果、事后放宽 band 或擅自新增 GPU 试次。本次总体 C2 不据此宣告 PASS。

## 重算

输出包含四臂输入哈希、完整原生序列、两对差值及 DCP coverage。仅对本次可信 checkpoint 运行；`.metadata` 使用 pickle，不能接受不可信输入。拒绝覆盖既有输出。

```bash
python3 evidence/tools/native_secondary_audit_927c5de.py \
  --campaign /root/autodl-tmp/task11-3090/formal/parameter-measurement-4c74209 \
  --out /tmp/P_NATIVE_SECONDARY_AUDIT_REPLAY.json
python3 -m pytest -q -p no:cacheprovider \
  evidence/tools/test_native_secondary_audit_927c5de.py
```

已归档输出：`gpu_campaign/task11_3090/c2_parameter/P_NATIVE_SECONDARY_AUDIT.json`。大参数原件仍在本地；公开下载与完整第三方复算另行验收。
