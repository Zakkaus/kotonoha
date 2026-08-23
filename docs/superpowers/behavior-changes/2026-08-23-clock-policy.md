# Cider clock policy

- `case_id`: `clock.cider-source-policy`
- `status`: `Accepted`
- `owner`: application clock coordinator
- `old_behavior`: 外部歌词显示时，当前 MPRIS provider 仍可能使用匹配的 Cider tick 校准共享 clock，行为由 gate/协调器路径决定。
- `new_contract`: 提供 `follow_lyrics_source` 和 `prefer_matching_cider` 两种 policy；Cider 同曲且 tick 有效时是否校准由设置决定。Cider 断线或 Position 不可用时保留歌词并回退 MPRIS。
- `user_impact`: 用户可以在“来源一致性”和“Cider 时间精度”之间选择，不会因 Cider 暂时断线丢失歌词。
- `reason`: 两种时钟来源各有明确优缺点，硬编码一种会牺牲另一类用户体验。
- `replacement_tests`: clock policy corpus、Cider disconnect/position-unavailable golden scenarios。
- `removal_condition`: 迁移完成后删除 MPRIS provider 直接读取 gate timing 的兼容路径。
