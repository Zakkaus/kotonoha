# 歌词 resolution policy

## `resolution.default-ordered-first`

- `case_id`: `resolution.default-ordered-first`
- `status`: `Accepted`
- `owner`: application lyrics workflow
- `old_behavior`: Config 默认 `prefer_best_lyrics=True`，resolver 默认并发竞争多个网络来源并选择较高置信度结果。
- `new_contract`: 默认 `ordered_first`；来源顺序决定同一可接受等级的结果，`best_confidence` 作为显式可选 policy。
- `user_impact`: 默认本地优先、请求数量和结果选择更可预测；需要更高匹配置信度的用户可以主动选择另一策略。
- `reason`: 当前默认并发竞争与“来源优先级”冲突，且 resolver 内部决定 policy 会让配置和测试无法表达真实意图。
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
