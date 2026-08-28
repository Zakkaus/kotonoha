# 歌词 resolution policy

## `resolution.default-best-confidence`

- `case_id`: `resolution.default-best-confidence`
- `status`: `Accepted`
- `owner`: application lyrics workflow
- `old_behavior`: Config 默认 `prefer_best_lyrics=True`，resolver 默认并发竞争多个网络来源并选择较高置信度结果。
- `new_contract`: 默认 `best_confidence`；启用 `prefer_best_lyrics` 时来源竞争并按置信度选择，关闭后使用 `ordered_first`，来源顺序决定结果。
- `user_impact`: 默认优先匹配质量最高的歌词；需要严格按来源顺序查询的用户可以在 Settings 中关闭该开关。
- `reason`: 用户需要在质量优先和顺序优先之间作出明确选择，来源顺序本身仍由 Settings 配置并持久化。
- `replacement_tests`: source plan precedence corpus、ordered/best policy contract tests。
- `removal_condition`: 迁移完成后删除 resolver 内部 `prefer_best` 分支和旧配置字段的直接解释逻辑。

## `resolution.medium-fallback`

- `case_id`: `resolution.medium-fallback`
- `status`: `Accepted`
- `owner`: application lyrics workflow / display policy
- `old_behavior`: sequential resolver 可以在遇到 `MEDIUM` artifact 后立即返回；best resolver 的等待规则由内部实现决定。
- `new_contract`: `MEDIUM` 先等待其他可能产生 `EXACT/HIGH` 的来源；没有更可靠结果时才作为候选显示。自动流程不持久化，用户确认后才保存。
- `user_impact`: 减少错误版本歌词直接替换正确结果的情况，同时保留“可能有歌词可看”的兜底。
- `reason`: 匹配分数只是证据，不等于用户已经确认了录音版本；自动缓存会把猜测长期固化。
- `replacement_tests`: confidence/source-plan corpus、manual selection contract tests。
- `removal_condition`: 迁移完成后删除 resolver 中由 provider 返回结果直接决定 active display 的路径。
