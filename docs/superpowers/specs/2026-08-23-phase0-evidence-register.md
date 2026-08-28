# Phase 0 Evidence Register

本登记是 `2026-08-23-kotonoha-architecture-refactor.md` 的 Phase 0 门禁。它把行为矩阵中的
`Retain` 行映射到实际的 public contract test，并把跨 owner 的 golden scenario 映射到当前基线
测试。测试必须通过公开构造和真实形状的 fake 验证输入、输出和失败语义；不能通过读取生产源代码
字符串来“证明”行为。

## 判断规则

- `Retain` 行至少有一个正向 contract test，并覆盖最近的失败、miss、timeout 或取消分支。
- title/parser rule 使用稳定的语义 `rule_id`，不把私有正则名称当成契约。每个 rule 在 typed corpus
  中有正向 case、近邻负向 variant 和 canonical public output。登记见
  `tests/behavior_rule_inventory.py`，门禁见 `tests/test_behavior_corpus.py`。
- `covered` 表示当前实现的 public test 已执行；`corpus` 表示还进入了 differential corpus；`target`
  表示 Phase 1 的目标契约已经确定，但当前实现尚未迁移，不能伪装成已实现。

## Lyrics Retain Contracts

| 矩阵行 | Public contract test | 覆盖的失败或边界 |
| --- | --- | --- |
| `#26` | `tests/test_titles.py::test_fixture_recovers_artists_carried_by_titles`; `tests/test_titles.py::test_fixture_title_pairs_are_never_split`; `tests/test_mpris.py::test_parse_recovers_artist_from_title_without_splitting_artist_field` | 无分隔证据不恢复；双语标题不拆成 artist/title |
| `#33` | `tests/test_lyrics.py::test_explicit_live_version_conflict_is_rejected`; `tests/test_lyrics.py::test_best_match_prefers_duration`; `tests/test_lyrics.py::test_every_outcome_names_the_rule_that_produced_it`; `tests/test_lyrics.py::test_the_refusal_that_dominates_is_the_one_reported` | 版本冲突、置信度、排序和拒绝原因分开 |
| `#34` | `tests/test_lyrics_local.py::test_loads_utf8_sidecar`; `tests/test_lyrics_local.py::test_missing_sidecar_is_a_miss`; `tests/test_lyrics_local.py::test_empty_sidecar_is_a_miss`; `tests/test_lyrics_local.py::test_untimed_sidecar_is_a_miss`; `tests/test_lyrics_local.py::test_sidecar_symlink_outside_audio_directory_is_a_miss`; `tests/test_lyrics_local.py::test_sidecar_offset_tag_shifts_the_timings` | 缺失、空、无 timed lines、越界路径是 Miss；offset 保留 |
| `#36` | `tests/test_lyrics_local.py::test_sidecar_wins_over_embedded_tag`; `tests/test_lyrics_local.py::test_loads_embedded_vorbis_lyrics`; `tests/test_lyrics_local.py::test_loads_embedded_id3_uslt`; `tests/test_lyrics_local.py::test_loads_embedded_mp4_lyrics`; `tests/test_lyrics_local.py::test_plain_embedded_lyrics_is_a_miss` | sidecar 优先；可选依赖/tag miss 区分；普通文本不展示 |
| `#37` | `tests/test_lyrics_hint.py::test_known_hint_rules`; `tests/test_lyrics_hint.py::test_unknown_or_malformed_players_yield_no_hint`; `tests/test_lyrics_resolver.py::test_exact_qqmusic_hint_fetches_only_when_source_is_enabled` | 已知 hint 才进入 provider；未知、malformed 或 disabled 不请求 |
| `#39` | `tests/test_player_selection.py::test_a_newer_player_wins_when_both_name_a_performer`; `tests/test_player_selection.py::test_a_locked_player_is_followed_even_while_paused`; `tests/test_player_selection.py::test_nothing_playable_selects_nothing`; `tests/test_settings_dialog.py::test_detected_players_are_readable_and_store_bus_name` | runtime/settings 共享选择规则；paused、lock、无可播放对象 |
| `#40` | `tests/test_lyrics_krc.py::test_parse_krc_decodes_fixture_and_makes_word_times_absolute`; `tests/test_lyrics_krc.py::test_parse_krc_rejects_undecodable_body`; `tests/test_lyric_formats.py::test_parse_yrc_word_timing`; `tests/test_lyrics.py::test_kugou_undecodable_krc_falls_back_to_lrc` | word timing、坏 KRC、provider fallback |
| `#42` | `tests/test_mpris.py::test_the_non_song_gate_reads_what_the_player_reported`; `tests/test_mpris_provider.py::test_non_song_never_reaches_the_resolver` | gate 使用 raw title；非歌曲不进入 resolver |
| `#45` | `tests/test_config.py::test_invalid_json_returns_defaults`; `tests/test_config.py::test_a_failed_save_leaves_the_previous_configuration_intact`; `tests/test_config.py::test_an_unreadable_config_is_kept_rather_than_overwritten`; `tests/test_config.py::test_a_config_that_is_not_utf8_does_not_end_startup`; `tests/test_config.py::test_a_pipe_at_the_config_path_does_not_block_startup`; `tests/test_config.py::test_a_number_too_large_for_an_int_falls_back_to_the_default` | 损坏、不可读、FIFO、超大数字不会覆盖旧状态或阻断启动 |
| `#49` | `tests/test_lyrics_providers.py::test_every_provider_refuses_an_unbounded_response`; `tests/test_lyrics_providers.py::test_a_body_larger_than_one_read_arrives_whole`; `tests/test_lyrics_krc.py::test_a_krc_that_expands_without_bound_is_refused` | response/body/解压预算；不能把 HTTP 200 或部分 body 当成功 |
| `#50` | `tests/test_lyrics_local.py::test_a_pipe_where_the_sidecar_should_be_does_not_wedge_the_reader`; `tests/test_lyrics_local.py::test_a_pipe_where_the_audio_file_should_be_is_not_handed_to_the_tag_reader`; `tests/test_lyrics_resolver.py::test_a_local_lyric_read_does_not_hold_the_event_loop`; `tests/test_lyrics_resolver.py::test_the_resolver_can_stop_the_work_it_started` | regular file 边界、worker ownership、shutdown |
| `#51` | `tests/test_titles.py::test_a_chinese_version_marker_is_read_as_a_version`; `tests/test_titles.py::test_the_studio_pressing_is_not_a_version_conflict`; `tests/test_lyrics.py::test_explicit_live_version_conflict_is_rejected`; `tests/test_lyrics.py::test_version_markers_conflict_in_both_directions` | 只认结尾 marker；普通词和 studio pressing 不误判 |
| `#56` | `tests/test_lyrics_krc.py::test_a_timestamp_too_large_for_a_float_skips_its_line`; `tests/test_lyric_formats.py::test_a_yrc_timestamp_too_large_for_a_float_skips_its_line`; `tests/test_lyric_formats.py::test_parse_lrc_lines_and_end_times` | 极端 timestamp 只丢坏行；line/word 范围保持 canonical |
| `#57` | `tests/test_lyrics_resolver.py::test_concurrent_identical_requests_share_network_work`; `tests/test_lyrics_resolver.py::test_one_caller_leaving_does_not_cancel_the_other`; `tests/test_lyrics_resolver.py::test_the_resolver_can_stop_the_work_it_started` | shared task、caller cancellation、owner shutdown 分开 |
| `#58` | `tests/test_lyric_formats.py::test_merge_translation_by_nearest_time`; `tests/test_lyric_formats.py::test_merge_translation_out_of_tolerance_left_blank`; `tests/test_lyric_formats.py::test_translation_merging_stays_cheap_as_a_provider_sends_more_lines` | nearest、tolerance、线性增长边界 |
| `#61` | `tests/test_mpris_session.py::test_a_failed_detail_read_still_names_the_player`; `tests/test_mpris_session.py::test_an_unreachable_player_is_not_a_player`; `tests/test_mpris_session.py::test_a_read_that_never_answers_gives_up` | detail error、unreachable、deadline 不阻塞 poll |
| `#63` | `tests/test_receiver.py::test_tick_frame_calibrates_clock_only`; `tests/test_receiver.py::test_closed_gate_retains_tick_without_publishing_cider_content`; `plugins/cider/lyrics/src/__tests__/transport.test.ts::it("retries an attempt that never leaves CONNECTING")`; `plugins/cider/lyrics/src/__tests__/transport.test.ts::it("drops a frame rather than queueing it behind a stalled receiver")` | Cider clock/ownership、CONNECTING timeout、send buffer 上限 |

## Overlay Retain Contracts

| 矩阵行 | Public contract test | 覆盖的失败或边界 |
| --- | --- | --- |
| `#25` | `tests/test_platform_detect.py::test_should_disable_layer_shell_on_gnome_wayland`; `tests/test_platform_detect.py::test_should_not_disable_layer_shell_on_kde_wayland`; `tests/test_architecture.py::test_desktop_environment_has_one_reader` | platform fact 只由 probe 读取；GNOME/KDE/X11 分支 |
| `#28` | `tests/test_architecture.py::test_overlay_contracts_is_toolkit_free`; `tests/test_overlay_platform.py::test_the_qt_host_implements_every_method_the_contract_names` | contract 不带 Qt；native handle 留在 adapter |
| `#29` | `tests/test_overlay_platform.py::test_a_drag_is_not_persisted_where_the_window_cannot_be_placed`; `tests/test_overlay_platform.py::test_a_drag_whose_update_failed_is_not_persisted`; `tests/test_platform_registry.py::test_a_wayland_fallback_drag_reports_that_nothing_moved` | rejected/failed move 不持久化 |
| `#30` | `tests/test_platform_registry.py::test_the_blur_object_is_released_before_its_surface_is_destroyed`; `tests/test_platform_registry.py::test_a_returning_output_does_not_rebuild_a_closed_overlay`; `tests/test_platform_registry.py::test_a_returning_output_that_cannot_be_rebuilt_stays_owed`; `tests/test_overlay_platform.py::test_placeholder_screen_is_never_adopted_while_every_output_is_gone` | blur/surface/output owner、closed callback、rebind failure |
| `#31` | `tests/test_platform_registry.py::test_provider_order_selects_layer_shell_before_fallbacks`; `tests/test_platform_registry.py::test_the_settings_window_gets_the_same_adapter_the_session_selects` | composition root 单次选择；settings/overlay 共用 adapter |
| `#35` | `tests/test_platform_registry.py::test_layer_shell_registry_keeps_default_strategy_for_kde`; `tests/test_platform_registry.py::test_layer_shell_registry_selects_niri_from_session_desktop`; `tests/test_platform_registry.py::test_an_empty_drag_provider_tuple_is_not_a_missing_one` | compositor-specific drag strategy 与 probe 解耦 |
| `#38` | `tests/test_overlay.py::test_offset_buttons_shift_sweep_and_hide_with_lock`; `tests/test_overlay.py::test_track_without_offset_uses_global_lead`; `tests/test_config.py::test_track_offsets_roundtrip_and_evict_oldest` | offset key、eviction、global lead 与 apply timing |
| `#39` | `tests/test_player_selection.py::test_the_current_player_is_polled_first`; `tests/test_settings_dialog.py::test_resetting_the_sources_page_restores_automatic_player_selection` | runtime/settings 不各自复制 selection policy |
| `#44` | `tests/test_platform_registry.py::test_provider_order_selects_layer_shell_before_fallbacks`; `tests/test_platform_registry.py::test_layer_shell_operations_report_failure_when_the_capability_is_off`; `tests/test_platform_detect.py::test_overlay_mode_available_on_x11_without_layer_shell` | deterministic fake 与环境 probe 分开；live compositor 不作为 Python 单测前提 |
| `#46` | `tests/test_karaoke.py::test_the_sweep_follows_a_line_with_no_separators`; `tests/test_karaoke.py::test_word_fill_fractions`; `tests/test_overlay.py::test_fit_mode_gives_a_large_font_room_for_a_whole_line`; `tests/test_karaoke.py::test_the_interlude_marker_is_a_row_the_sweep_runs_across` | 无空格文字、word progress、interlude、font fit |
| `#47` | `tests/test_config.py::test_all_font_sizes_clamp_to_the_spin_box_range`; `tests/test_config.py::test_typography_and_panel_size_defaults_and_clamps`; `tests/test_settings_dialog.py::test_opening_settings_does_not_narrow_a_saved_sync_offset` | Config/form 共用范围；打开 settings 不静默截断 |
| `#54` | `tests/test_settings_focus.py::test_focused_input_renders_the_configured_accent_ring` | 焦点反馈以实际渲染像素验证，不以 CSS 文本存在代替 |
| `#55` | `tests/test_platform_registry.py::test_a_deleted_widget_reports_no_handle_rather_than_raising`; `tests/test_native.py::test_blur_objects_do_not_accumulate_across_surface_rebuilds`; `tests/test_native.py::test_missing_library_disables_with_a_hint` | late callback、删除 widget、bridge failure |
| `#60` | `tests/test_platform_registry.py::test_a_failed_output_move_stays_owed_so_a_later_event_retries`; `tests/test_platform_registry.py::test_layer_shell_rebuilds_on_returning_output_after_release`; `tests/test_overlay_platform.py::test_released_cross_output_keeps_margin_x_and_records_output` | pending output intent、rebind、位置提交 |

## Grammar / Parser Rule Gate

当前可执行 corpus 的 rule inventory 如下。`lrc.rejected_not_truncated` 特意记录当前实现的冻结
baseline：它不是新目标行为；Phase 1 实现 `#62` 时必须通过 `BehaviorChangeRecord` 改为明确拒绝，不能
只改 expected。

| Rule group | Positive case IDs | Nearest negative evidence |
| --- | --- | --- |
| title | `title.platform-credit`, `title.version-suffix`, `title.title-pair-not-credit` | 每个 case 的 `negative_variants[0]` |
| LRC | `lrc.basic-lines`, `lrc.offset-and-bound`, `lrc.multiple-tags-and-end`, `lrc.max-lines-reject` | untimed/absurd offset/missing content/under-budget line count |
| YRC | `yrc.word-timing`, `yrc.timestamp-bound` | metadata-only/non-word-timed line |
| KRC | `krc.decoded-word-timing`, `krc.timestamp-bound`, `krc.decompression-budget` | bad magic, malformed timestamp line, under-budget valid body |

`tests/test_behavior_corpus.py::test_every_grammar_rule_has_a_public_case_and_nearest_negative` 要求
登记的 rule id 与 corpus 实际使用的 rule id 完全相同；缺登记、无负向 variant 或正向 case 不存在时测试
失败。当前实现的全部 corpus projection 已通过 differential comparator。

## Golden Scenario Execution

下表对应 `2026-08-23-kotonoha-golden-scenarios.md` 的场景目录。`covered`/`corpus` 场景由现有
Python/Vitest 测试执行；`target` 场景只验证决策记录和当前实现的边界，Phase 1 新 owner 落地时必须
沿用同一 scenario id 再执行一次。

| Scenario | 当前执行入口 | 状态 |
| --- | --- | --- |
| `playback.queue-position` | `tests/test_mpris_provider.py::test_cumulative_position_offset_realigns_the_sweep`; `tests/test_mpris_provider.py::test_cumulative_player_not_miscalibrated_by_normal_advance` | covered |
| `identity.mixed-metadata` | `tests/test_mpris_provider.py::test_metadata_changed_during_sample_is_discarded`; `tests/test_mpris.py::test_new_title_old_artist_does_not_commit_before_stable_pair` | covered |
| `title.raw-noise-and-version` | title corpus；`tests/test_titles.py::test_noisy_title_queries_strip_fused_cjk_upload_noise`; `tests/test_lyrics.py::test_explicit_live_version_conflict_is_rejected` | corpus |
| `resolution.exact-id` | `tests/test_lyrics_resolver.py::test_exact_netease_hint_bypasses_matching`; `tests/test_lyrics_resolver.py::test_failed_exact_hint_falls_back_to_search`; `tests/test_lyrics_resolver.py::test_exact_qqmusic_hint_fetches_only_when_source_is_enabled` | covered |
| `resolution.local-sources` | `tests/test_lyrics_resolver.py::test_local_hint_wins_without_using_sources_or_network`; `tests/test_lyrics_resolver.py::test_local_hint_falls_back_to_normal_resolution_when_sidecar_is_empty`; local source tests | covered |
| `resolution.default-best-confidence` | `tests/test_lyrics_resolver.py::test_best_mode_prefers_higher_confidence_over_first_source`; policy BehaviorChangeRecord | corpus/target |
| `resolution.manual-selection-priority` | `docs/superpowers/behavior-changes/2026-08-23-manual-lyrics-selection.md` | target |
| `resolution.medium-fallback` | `tests/test_lyrics_resolver.py::test_best_mode_medium_cider_does_not_block_a_network_high`; `tests/test_lyrics_resolver.py::test_best_mode_prefers_higher_confidence_over_first_source` | corpus/target |
| `provider.payload-budget` | provider body tests；KRC decompression budget corpus | covered/corpus |
| `resolution.shared-cancellation` | `tests/test_lyrics_resolver.py::test_concurrent_identical_requests_share_network_work`; `tests/test_lyrics_resolver.py::test_one_caller_leaving_does_not_cancel_the_other`; `tests/test_lyrics_resolver.py::test_the_resolver_can_stop_the_work_it_started` | covered |
| `cider.ownership-and-generation` | gate corpus；`tests/test_gate.py::test_closed_gate_retains_matching_snapshot_without_publishing`; `tests/test_receiver.py::test_closed_gate_retains_tick_without_publishing_cider_content`; Cider transport tests | corpus |
| `clock.cider-source-policy` | clock corpus；`tests/test_clock.py::test_sync_without_media_time_is_noop`; `tests/test_mpris_provider.py::test_matching_cider_tick_drives_external_line_selection` | corpus/target |
| `display.resolution-state-names` | display BehaviorChangeRecord；`tests/test_select.py::test_build_snapshot_empty_lines` | target |
| `display.timeline` | display corpus；`tests/test_karaoke.py::test_the_interlude_marker_is_a_row_the_sweep_runs_across`; `tests/test_overlay.py::test_fit_mode_gives_a_large_font_room_for_a_whole_line` | covered/corpus |
| `parser.format-boundaries` | LRC/YRC/KRC corpus；format and provider budget tests | corpus/target |
| `overlay.output-lifecycle` | platform registry output/rebind tests；`tests/test_native.py::test_blur_objects_do_not_accumulate_across_surface_rebuilds` | covered |
| `overlay.drag-failure` | `tests/test_overlay_platform.py::test_a_drag_is_not_persisted_where_the_window_cannot_be_placed`; platform failure corpus | covered/corpus |
| `lifecycle.restart-replacement-failure` | `tests/test_controller.py::test_a_restart_that_cannot_start_the_replacement_stays_up` | covered |

## Phase 0 Result

矩阵决策、Retain contract 覆盖、语义 grammar/parser rule corpus、differential baseline、BehaviorChangeRecord
和当前实现的 golden baseline 均已登记并执行。`target` 只表示 Phase 1 的实现工作，不再阻塞 Phase 0
的行为盘点与目标决策；后续迁移必须继续使用这些 scenario/case id，出现未登记差异时停止合并。
