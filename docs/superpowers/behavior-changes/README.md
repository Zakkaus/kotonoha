# BehaviorChangeRecord

行为变化必须先登记，再更新 corpus 的目标结果。记录不是提交说明的替代品，而是行为等价性门禁
需要的公共契约变更证据。

每条记录必须包含：

- `case_id`：对应 typed behavior corpus 或 golden scenario 目录的稳定 id；
- `status`：`Proposed`、`Accepted` 或 `Implemented`；
- `owner`：负责新行为的 feature/application owner；
- `old_behavior`：当前实现通过公开接口表现出的结果；
- `new_contract`：目标输入、输出和失败语义；
- `user_impact`：用户能观察到什么变化，以及为什么接受它；
- `reason`：为什么旧行为不是要继续保护的契约；
- `replacement_tests`：新契约和差异比较的测试入口；
- `removal_condition`：仅兼容迁移代码需要，说明何时可以删除旧路径。

没有记录的 baseline 差异视为回归。只修改 expected 让测试通过不构成行为变化记录。

当前记录：

- [#62 LRC 行数上限](2026-08-23-62-lrc-cap.md)
- [#62 restart failure](2026-08-23-62-restart-failure.md)
- [resolution policy](2026-08-23-resolution-policy.md)
- [用户确认歌词](2026-08-23-manual-lyrics-selection.md)
- [歌词解析展示状态](2026-08-23-display-resolution-states.md)
- [Cider clock policy](2026-08-23-clock-policy.md)
