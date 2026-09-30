# 测量臂的 observer 生效检查

在首个 ON 前固定本检查。不将环境开关本身视为 observer 已运行的证据，也不把旧 16 步实验的 2112 条上报硬套到 48 步臂。

- 每个 ON 臂须有非空 envelope JSONL，rank 集合为 `{0,1,2,3}`；每个 rank 至少有一条有限、非负 `device_ms` 且阶段名非空的设备测量。
- 四份 rank runtime 快照须表明 enabled、started 和 device timing enabled；归档 observer 错误、丢弃与超时计数。训练中 `closed=false` 不能单独证明退出清理失败。
- collector envelope 计数须与归档 JSONL 总行数匹配；归档 aligned ranks、invalid device samples、invalid packets 和 ingest errors。
- OFF 臂不得产生 observer envelope；日志须记录关闭状态。
- 若 ON 路径未被行使，不发布参数 ON/OFF 验收 PASS；保留原因和原件，不追加试次求通过。

本检查只证明比较确实覆盖 OFF/ON 两种运行路径，不改变参数容差、不评价 C1 开销或 C3 平台实时性。
