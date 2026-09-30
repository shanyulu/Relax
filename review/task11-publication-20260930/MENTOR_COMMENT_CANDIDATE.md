本地更新候选；拟替换 #357 既有评论 5888804136，不新增评论，当前未发布。

参数正式测量已完成：产品 `927c5de`，4×3090，四个 OFF 校准臂与两对 OFF/ON 测量；`116d527` 判定最终 checkpoint 在冻结包络内 PASS。独立覆盖审查确认 13 个有内容浮点 storage；169 项为空占位，48 个非张量叶未比较，不称完整 optimizer 恢复状态等价。本轮 loss／grad 没有 ON 前冻结的同版 band，仍为 UNSCORED，不能把参数通过改写成整体 C2 通过。

仍请确认：

1. C1 以 `perf/train_time` 还是 whole-job wall-clock 为主指标；确认前不启动 confirmatory。
2. rollout-cadence 的 TensorBoard 确认指标是否满足实时上报；JSONL 阶段定位与平台汇总不能逐事件 join，时延仍 UNMEASURED。
3. attention/MoE 本期是否接受 schema-only；当前真机证据仅单机 dense DP4，PP>1 平台汇总归属未闭合。
4. 对本轮 C2，是否接受最终参数、有限数值、更新与 token/LR 一致作为 loss／grad 的替代验收；若不接受，另立独立协议，先校准并冻结 band，再做新 ON，不事后补容差。

大参数与新 trace 归档保留本地；公开存储和跨位置恢复尚未闭环。此前“需要再取得空间并做正式参数训练”已过时，应更新为原件交付与范围验收待确认。
