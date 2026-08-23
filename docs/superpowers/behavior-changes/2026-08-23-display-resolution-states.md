# 歌词解析展示状态

- `case_id`: `display.resolution-state-names`
- `status`: `Accepted`
- `owner`: display/application workflow
- `old_behavior`: `LyricsSnapshot.found=False` 同时表示没有曲目、仍在查找和查找结束但没有歌词。
- `new_contract`: 使用 `NoTrack`、`Resolving`、`LyricsAvailable`、`LyricsNotFound`；界面使用“找不到歌词”。当前行、transition 和 interlude 属于 frame/timeline 内容，不建立 `Finished`。
- `user_impact`: 用户能区分正在查找和确实找不到歌词，最后一句结束也不会引入没有实际意义的伪状态。
- `reason`: 一个 bool 无法表达 workflow 阶段，导致旧歌词残留、空白和重试入口行为混淆。
- `replacement_tests`: display state corpus、loading/not-found transition tests、existing timeline/select tests。
- `removal_condition`: 迁移完成后删除 `LyricsSnapshot.found` 作为 workflow state 的兼容解释。
