# Task 11 参数 checkpoint 非张量状态审查

- 审查状态：`AUDIT_COMPLETE`；字段等价判定：`DIFFERENCES_FOUND`
- 产品：`927c5de2f5a8f307cad0c87f2c7eb2b78262334d`
- 每臂真实读取并核对的非张量叶：48
- 读取来源：四个测量臂各自哈希验证后的 `adapted_raw/converted.pt`；每次只加载一个臂。

## 覆盖结果

| 测量对      | 完全相同叶数 | 覆盖叶数 |
| ----------- | -----------: | -------: |
| P-M1 OFF/ON |           47 |       48 |
| P-M2 OFF/ON |           47 |       48 |

## 唯一差异叶：训练参数 `args`

其余 47 个非张量叶在四臂间完全一致。`args` 中每个配对的 14 个不同字段均属于运行身份：`rollout_result_dir`、`save`、`tb_experiment_name`，以及 TransferQueue 的 4 个存储实例 ID／`put_get_socket` 端口和 controller ID／两个端口。没有其他配置字段差异；逐臂的嵌套路径和 SHA-256 见 JSON。

iteration 为 47，两个 optimizer param group 的 step 均为 48。scheduler 步数、学习率和权重衰减参数，以及 optimizer 的 betas、eps、lr、weight decay 和 flags，均包含在四臂相同的 47 个叶中。这不证明完整恢复流程或全部 checkpoint 状态等价。

## 差异

| checkpoint 叶                                                                                                       | 类型                 | M1 相同 | M2 相同 | 四臂相同 | 差异说明                                                                                              |
| ------------------------------------------------------------------------------------------------------------------- | -------------------- | ------: | ------: | -------: | ----------------------------------------------------------------------------------------------------- |
| `common_state/shard_0_1[0].args`                                                                                    | `argparse.Namespace` |      否 |      否 |       否 | P-M1-on: 14 个 args 字段路径不同; P-M2-on: 14 个 args 字段路径不同; P-M2-off: 14 个 args 字段路径不同 |
| `common_state/shard_0_1[0].checkpoint_version`                                                                      | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `common_state/shard_0_1[0].content_metadata.chained_optim_avoid_prefix`                                             | `bool`               |      是 |      是 |       是 | —                                                                                                     |
| `common_state/shard_0_1[0].content_metadata.distrib_optim_sharding_type`                                            | `str`                |      是 |      是 |       是 | —                                                                                                     |
| `common_state/shard_0_1[0].content_metadata.singleton_local_shards`                                                 | `bool`               |      是 |      是 |       是 | —                                                                                                     |
| `common_state/shard_0_1[0].iteration`                                                                               | `int`                |      是 |      是 |       是 | —                                                                                                     |
| `common_state/shard_0_1[0].num_floating_point_operations_so_far`                                                    | `int`                |      是 |      是 |       是 | —                                                                                                     |
| `common_state/shard_0_1[0].opt_param_scheduler.end_wd`                                                              | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `common_state/shard_0_1[0].opt_param_scheduler.lr_decay_steps`                                                      | `int`                |      是 |      是 |       是 | —                                                                                                     |
| `common_state/shard_0_1[0].opt_param_scheduler.lr_decay_style`                                                      | `str`                |      是 |      是 |       是 | —                                                                                                     |
| `common_state/shard_0_1[0].opt_param_scheduler.lr_warmup_steps`                                                     | `int`                |      是 |      是 |       是 | —                                                                                                     |
| `common_state/shard_0_1[0].opt_param_scheduler.max_lr`                                                              | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `common_state/shard_0_1[0].opt_param_scheduler.min_lr`                                                              | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `common_state/shard_0_1[0].opt_param_scheduler.num_steps`                                                           | `int`                |      是 |      是 |       是 | —                                                                                                     |
| `common_state/shard_0_1[0].opt_param_scheduler.start_wd`                                                            | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `common_state/shard_0_1[0].opt_param_scheduler.wd_incr_steps`                                                       | `int`                |      是 |      是 |       是 | —                                                                                                     |
| `common_state/shard_0_1[0].opt_param_scheduler.wd_incr_style`                                                       | `str`                |      是 |      是 |       是 | —                                                                                                     |
| `common_state/shard_0_1[0].optimizer.param_state_sharding_type`                                                     | `str`                |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[0].betas[0]`                              | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[0].betas[1]`                              | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[0].bias_correction`                       | `bool`               |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[0].default_config`                        | `bool`               |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[0].eps`                                   | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[0].is_decoupled_lr`                       | `bool`               |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[0].is_expert_parallel`                    | `bool`               |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[0].lr`                                    | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[0].lr_mult`                               | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[0].max_lr`                                | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[0].min_lr`                                | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[0].step`                                  | `int`                |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[0].wd_mult`                               | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[0].weight_decay`                          | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[1].betas[0]`                              | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[1].betas[1]`                              | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[1].bias_correction`                       | `bool`               |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[1].default_config`                        | `bool`               |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[1].eps`                                   | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[1].is_decoupled_lr`                       | `bool`               |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[1].is_expert_parallel`                    | `bool`               |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[1].lr`                                    | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[1].lr_mult`                               | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[1].max_lr`                                | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[1].min_lr`                                | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[1].step`                                  | `int`                |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[1].wd_mult`                               | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.optimizer/shard_0_1[0].param_groups[1].weight_decay`                          | `float`              |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.per_bucket_numel/shard_0_1[0][0].(torch.bfloat16, torch.float32)[0]`          | `int`                |      是 |      是 |       是 | —                                                                                                     |
| `optimizer.distributed.dp_group_idx_0.per_bucket_numel_unpadded/shard_0_1[0][0].(torch.bfloat16, torch.float32)[0]` | `int`                |      是 |      是 |       是 | —                                                                                                     |

## 判读边界

- Only the four named measurement-arm raw converted payloads were loaded; no DCP re-conversion was performed.
- Semantic equality covers these 48 non-tensor leaves only; it does not establish full optimizer or scheduler restoration equivalence.
- torch.load(weights_only=False) is code-execution capable; inputs were accepted only after exact local campaign path, adapter lineage, raw hash, and source DCP tree hash checks.
- No GPU was used; one arm was loaded at a time with mmap; no payload copies were created.
