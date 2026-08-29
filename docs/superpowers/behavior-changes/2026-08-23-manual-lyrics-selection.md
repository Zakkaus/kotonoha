# 用户确认歌词

- `case_id`: `resolution.manual-selection-priority`
- `status`: `Accepted`
- `owner`: lyrics application workflow / local lyrics management UI
- `old_behavior`: 当前没有稳定的用户选择记录；普通 cache 命中按原 provider 位置参与解析。
- `new_contract`: 用户从候选中确认的歌词保存为本地确认结果，优先于 sidecar、embedded、exact hint、Cider 和 network；清除后恢复自动解析。
- `user_impact`: 自动匹配错误时用户可以明确指定版本，并且后续播放不会再次被错误候选覆盖。
- `reason`: 用户意图必须高于机器推断；普通自动 cache 不能冒充用户确认。
- `search_unavailable_contract`: 手动搜索 response 对未能回答的 provider 保留 `source` 与 `reason`，搜索窗口展示具体不可用原因。
- `replacement_tests`: `tests/test_lyrics_cache.py::test_manual_lookup_returns_the_latest_matching_selection_across_providers`、
  `tests/test_lyrics_resolver.py::test_manual_cache_selection_precedes_exact_hint_and_network`、
  `tests/test_lyrics_resolver.py::test_manual_cache_selection_is_used_by_ordinary_resolution`、
  `tests/test_lyrics_search.py::test_search_controller_reopens_after_real_dialog_closes`。
- `removal_condition`: 不适用；这是新增稳定能力。
