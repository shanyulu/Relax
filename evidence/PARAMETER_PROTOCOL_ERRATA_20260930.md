# 参数协议措辞勘误：数值相等不等于位相等

原冻结协议 `C2_PARAMETER_PROTOCOL_927C5DE.md` §2 将 exact-equal tensor count 定义为“bit-equal payloads”。实际冻结比较器与 bounded 等价执行器使用逐元素数值 `==`，不是 payload 字节比较。

## 正确读法

- `exact_equal` 应读为“canonical payload 的逐元素数值相等”。例如 `+0.0 == -0.0`，但其二进制表示不同。
- BF16 在 inventory 中被 canonicalize 为 float32；dtype 身份另行核对。数值相等不代表原始 checkpoint 文件逐字节相同。
- 169 个空占位项零元素，数值 equality 为 vacuous true，不能当作实质精度证据。
- 参数 PASS 仍由 **相同 key／shape／dtype 且每组 max-abs-delta 不超过先冻结容差** 决定；exact-equal count 是描述项，不影响此次 PASS 门槛。

本勘误不修改冻结协议、比较器、容差、结果 JSON 或已发布旧判定。后续正文统一使用“数值相等”，不再声称“位确定性”或“checkpoint 文件 bit-equal”。若以后需要位相等验收，必须新预注册原始表示、比较方法与判定，不能追改本实验定义。

来源：`evidence/tools/c2_parameter_bounded_927c5de.py` 中 `exact = exact and a == b`；回归 `test_numeric_equality_is_not_bit_equality` 明确保留 signed-zero 反例。
