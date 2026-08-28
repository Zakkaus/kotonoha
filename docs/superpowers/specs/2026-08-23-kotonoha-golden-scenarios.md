# Kotonoha Golden Scenarios

这是 Phase 0 的场景目录。每个场景描述跨模块边界的公开输入、公开结果和失败语义，作为后续
feature contract、迁移比较和回归测试的索引。`covered` 表示现有测试已经保护；`corpus` 表示
已经进入 `BehaviorCase`；`target` 表示目标契约已确定，但要等 Phase 1 的新 owner/API 落地。

场景不能通过读取源代码、私有字段或 task identity 来验证。需要 Qt、真实 compositor、D-Bus、网络
或线程池的场景，使用真实形状的 fake，并在测试报告中保留环境限制。

| ID | 公开输入 | 公开结果与失败语义 | 当前证据 | 状态 |
| --- | --- | --- | --- | --- |
| `playback.queue-position` | 连续两个 track identity；播放器 Position 使用 queue cumulative length/position，随后重置到新歌起点。 | 新 track 只在稳定身份提交后生成；相对歌曲位置修正为正确值；空或混合 metadata 不提交新歌。 | `tests/test_mpris.py`、`tests/test_mpris_provider.py` | covered |
| `identity.mixed-metadata` | 同一采样期间 title、artist 或 duration 前后不一致。 | 丢弃不一致采样，不能把旧 artist 与新 title 拼成一个可解析 track；稳定窗口后才继续。 | `test_mpris_provider.py::test_metadata_changed_during_sample_is_discarded`、`tests/test_mpris.py` | covered |
| `title.raw-noise-and-version` | raw title 含 uploader、平台后缀、频道噪声或版本 marker，同时保留 raw artist。 | normalized lookup view 去除平台噪声；版本冲突返回拒绝证据；不能因相似标题接受错误 recording。 | title corpus、`tests/test_titles.py`、`tests/test_lyrics.py` | corpus |
| `resolution.exact-id` | 精确 provider song id 成功、失败、source 未启用。 | 成功时绕过无关 search；失败时继续配置来源；source 未启用时不发请求。 | `tests/test_lyrics_resolver.py` | covered |
| `resolution.local-sources` | sidecar、embedded、网络来源同时存在；sidecar 缺失、为空或无 timed lines。 | sidecar 优先 embedded；本地 miss 不是异常，继续自动来源；普通文本不进入可展示歌词。 | `tests/test_lyrics_local.py`、`tests/test_lyrics_resolver.py` | covered |
| `resolution.default-best-confidence` | sidecar、embedded、exact hint、Cider 和 network 同时有候选；policy 为 `ordered_first` 或 `best_confidence`。 | 默认按置信度竞争；关闭 `prefer_best_lyrics` 后按来源顺序；cache 只加速所属来源，不改变优先级。 | `docs/superpowers/behavior-changes/2026-08-23-resolution-policy.md` | target |
| `resolution.manual-selection-priority` | 用户从多个候选中确认一个版本，然后再次播放同一音频；也覆盖清除确认。 | 用户确认结果最高优先；清除后恢复自动来源；普通自动 cache 不获得该优先级。 | `docs/superpowers/behavior-changes/2026-08-23-manual-lyrics-selection.md` | target |
| `resolution.medium-fallback` | 一个来源产生 `MEDIUM`，后续来源可能产生 `HIGH`；用户也可手动确认候选。 | 自动流程先等待更可靠来源；没有更可靠结果才显示候选；自动不持久化，确认后才保存。 | `tests/test_lyrics_resolver.py` 的 best-mode cases、BehaviorChangeRecord | corpus/target |
| `provider.payload-budget` | timeout、HTTP 200 错 payload、body 超限、压缩后超限。 | 分别报告 timeout、malformed 或 budget rejection；不能把 HTTP 200 当成功，也不能返回部分 payload。 | `tests/test_lyrics_providers.py`、`tests/test_lyrics_krc.py` | covered |
| `resolution.shared-cancellation` | 相同请求由两个 caller 共享；一个 caller 取消；owner shutdown。 | caller cancellation 不取消其他 caller；owner 显式取消并 await shared task；无 unowned work。 | `tests/test_lyrics_resolver.py` | covered |
| `cider.ownership-and-generation` | Cider selected/unselected、同曲 tick、断线、旧 snapshot/tick generation。 | external lyrics 不被 Cider content 抢回；匹配 tick 可以按 clock policy 使用；旧 generation 不更新当前歌曲。 | `tests/test_gate.py`、`tests/test_receiver.py`、`tests/test_mpris_provider.py`、gate corpus | corpus |
| `clock.cider-source-policy` | Position 暂不可读、Cider 断线、MPRIS 仍可用；分别选择两种 clock policy。 | 保留已找到歌词和最后有效位置；按 policy 选择 Cider 或歌词来源 clock，不可用时回退 MPRIS；不能变成 `LyricsNotFound`。 | `docs/superpowers/behavior-changes/2026-08-23-clock-policy.md`、`tests/test_clock.py`、`tests/test_mpris_provider.py` | corpus/target |
| `display.resolution-state-names` | 无曲目、已提交曲目但仍查找、找到歌词、搜索结束无歌词。 | 只使用 `NoTrack`、`Resolving`、`LyricsAvailable`、`LyricsNotFound`；界面显示“找不到歌词”；无 `Empty`/`Finished`。 | `docs/superpowers/behavior-changes/2026-08-23-display-resolution-states.md`、`tests/test_select.py` | target |
| `display.timeline` | line/word timing、无空格文字、interlude、歌曲结束、font fit。 | timeline 输出当前行或 interlude frame 内容；无歌词是 resolution state，不是 timeline 状态；renderer 按实际 layout 测量。 | `tests/test_lyric_formats.py`、`tests/test_karaoke.py`、`tests/test_select.py`、`tests/test_overlay.py`、display corpus | covered/corpus |
| `parser.format-boundaries` | LRC、YRC、KRC 的合法输入、metadata/blank、坏格式、超预算和极端 timestamp。 | canonical lines/word spans 保持稳定；坏输入或预算超限明确 miss/reject；不能静默截断成完整歌词。 | `tests/test_lyric_formats.py`、`tests/test_lyrics_krc.py`、parser corpus、#62 record | corpus/target |
| `overlay.output-lifecycle` | output unplug/replug、rebind failure、closed callback、blur/surface release。 | 资源按 owner 释放；失败带 reason 并保留 pending intent；Closed 后 deferred callback 不触碰 widget。 | `tests/test_platform_registry.py`、`tests/test_overlay_platform.py` | covered |
| `overlay.drag-failure` | compositor/client positioning 不可用，或 drag update/release 失败。 | 返回 rejected/failure；只有实际应用的位置才持久化；失败不能伪装为成功。 | `tests/test_overlay_platform.py`、platform corpus | covered/corpus |
| `lifecycle.restart-replacement-failure` | 替代进程启动成功或失败。 | 只有替代进程确认启动后当前实例才退出；失败保留当前实例并报告 reason。 | `tests/test_controller.py`、`docs/superpowers/behavior-changes/2026-08-23-62-restart-failure.md` | covered |

## 使用规则

1. Phase 1 新 owner 实现前，`target` 场景只允许增加契约，不允许把当前实现误当成最终行为。
2. 新实现接入后，同一场景必须通过 canonical public projection；未登记差异不能合并。
3. `BehaviorChangeRecord` 的 `case_id` 必须引用本目录或对应 typed corpus 的稳定 ID；改变 expected
   不是行为决策本身。
4. `covered` 只说明当前测试有证据，不代表新架构 owner 已经存在；新 owner 仍需重新运行同一场景。
