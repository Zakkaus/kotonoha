# 歌词相关 PR 行为矩阵

## Scope

- **目标**：还原最近 40 个提交中直接改变歌词获取、匹配、缓存、时间轴或时钟行为的 PR。
- **包含**：`#26`、`#32-#34`、`#36-#37`、`#40`、`#42`、`#45`、`#49-#51`、`#56-#59`、`#61-#64`，以及会影响歌词来源选择的 `#39`。
- **排除**：仅修改 packaging、settings 外观或平台测试运行方式的提交；它们在 Overlay 矩阵或总计划中说明。
- **证据**：对应 squash commit subject/body、commit diff 和当前 source/tests。

## 行为总图

```mermaid
flowchart LR
    playback["播放器观察\nMPRIS / Cider / 文件"] --> identity["稳定曲目身份\nraw + normalized + generation"]
    identity --> hint["精确提示\ntrack id / local path"]
    identity --> search["来源搜索\nprovider order / best policy"]
    hint --> document["歌词文档\nartifact + evidence"]
    search --> document
    document --> timeline["时间轴与时钟\nline / word / offset"]
    timeline --> display["LyricsState / display model"]
```

## PR 行为目录

| PR | 实际改变的行为（Observed） | 必须明确的行为契约 | 目标归属 |
| --- | --- | --- | --- |
| `#26` | 播放器 artist 是频道、label、studio 时，从标题前缀恢复 performer；只有 title grammar 提供分隔证据才恢复，避免把整段标题当 artist。 | raw artist、title grammar、recovered artist 是三个视图；恢复失败不能覆盖原始值；恢复规则不能由某个 provider 私有化。 | `domain/track_identity` 的 `ArtistEvidence` 与纯 `TitleGrammar` |
| `#32` | 读取 MPRIS `mpris:trackid`/`xesam:url`，对支持的播放器直接按 provider song id 获取歌词；失败或 provider 未启用时回退搜索。 | hint 是优化，不是死路；精确 id 命中可以跳过匹配，但结果仍必须经过 payload/歌词有效性校验。 | `infrastructure/mpris` 产出 `ProviderHint`；`application/lyrics` 编排 fallback |
| `#33` | 将候选排序从布尔链改为 artist/title/album 的加权相似度；明确相似度只排序，不能跨过版本冲突或低置信度门槛。 | `MatchEvidence`、`MatchConfidence`、`RankingScore` 分离；分数不能单独代表“可接受”。 | `domain/matching` |
| `#34` | `file://` 播放器提示触发同目录 `.lrc`；sidecar 优先网络；UTF-8/GB18030 解码；路径越界拒绝；支持 LRC offset。 | local source 的 precedence、路径信任边界、编码和 offset 必须是 source contract；缺失/无效 sidecar 是 `Miss`，不是异常。 | `infrastructure/local_lyrics` + `application/source_plan` |
| `#36` | 增加 mutagen 可选的内嵌歌词读取；sidecar > embedded > network；USLT/Vorbis/MP4 tag 都复用 LRC parser；普通文本不是可展示歌词。 | optional dependency 的 unavailable 与 source miss 分开；文件句柄只在 adapter 内管理；tag shape 统一转成 `LyricDocument`。 | `infrastructure/local_lyrics` |
| `#37` | 用播放器提供的 QQ Music song id 做精确获取，减少 title search。 | 每种 `ProviderHint` 都有 provider、song id、来源可信度；未支持 hint 不得污染搜索请求。 | `domain/provider_hint` + provider adapter |
| `#39` | 设置页播放器行显示 bus identity，选择逻辑同时考虑 metadata、playing/paused、连续性。 | player selection 是 application policy；MPRIS bus object 不能传到 settings/UI；列表展示使用 `PlayerInfo` DTO。 | `application/playback` + `presentation/settings` |
| `#40` | Kugou KRC 的 word-level timing 不再丢弃；压缩歌词解析成带词时间的 line。 | parser 负责结构和预算，不能决定 provider 匹配；word timing 不完整时有明确 line-level fallback。 | `domain/lyric_document` + `infrastructure/kugou` |
| `#42` | non-song gate 使用播放器报告的原始 title，而不是被清洗后的 title；修复 title cleaner 把 gate 所需证据丢掉的问题。 | raw metadata 永不被 normalized view 替换；gate 必须声明输入视图。 | `domain/track_identity` + `application/source_gate` |
| `#45` | 配置写入改为 atomic rename/fsync；损坏配置先 `.corrupt` 保留；FIFO、非 UTF-8、超大数字不会阻断启动。 | 配置 parse、persistence、default policy 分层；启动 fallback 结果必须可观测，不要让业务层处理原始 JSON。 | `infrastructure/config_store` + typed `Config` |
| `#49` | 网络 response、JSON body、KRC 解压都受上限；streaming body 必须读到结束再判断总量；缓存 payload 也要防压缩炸弹。 | 每个外部 source 使用统一 `BoundedBodyReader`/`PayloadDecoder`；上限属于边界 policy，不由 provider 忘记实现。 | `infrastructure/http_payload` |
| `#50` | player 提供的 `.lrc`/音频路径按 descriptor 检查 regular file，拒绝 FIFO；阻塞文件读取移出 UI/event loop，取消语义被记录。 | path 先验证再读取；读操作有 owner、预算和 shutdown 语义；取消 wrapper 不得被误称为取消底层阻塞工作。 | `infrastructure/local_lyrics` + `application/task_owner` |
| `#51` | version marker 只从标题结尾识别，避免正文中的普通词触发 live/remix/instrumental 等冲突。 | version extraction 输出结构化 qualifiers；cleaning 不能偷偷删除 qualifier；版本冲突是明确的 `Rejected` reason。 | `domain/title_grammar` |
| `#56` | KRC/YRC word timestamp 不能超过 line/track 合法范围，避免异常 provider 时间把高亮推到很远。 | parser 输出前做时间 invariant；`LyricDocument` 必须保证 line/word 顺序、范围和非负性。 | `domain/lyric_document` |
| `#57` | 相同 lookup 的多个 caller 共享 in-flight task；一个 caller cancel 不得取消其他 caller；owner shutdown 才能 cancel shared task。 | shared work 的 owner、caller cancellation、shutdown cancellation 三者必须分别建模和测试。 | `application/lyrics_resolution` |
| `#58` | translation merging 从每行扫描整轨改为更低复杂度，保持展示结果不变。 | 性能优化必须围绕不可变 `LyricDocument` 做索引；不得让 parser、merge、renderer 互相知道实现细节。 | `domain/translation_merge` |
| `#59` | 播放器暂停后恢复使用 player position，而不是本地估算位置，减少 pause/resume 漂移。 | clock 有多个 observation source；`ClockCoordinator` 必须明确 authoritative source、fallback 和校准窗口。 | `application/clock` + `domain/timeline` |
| `#61` | 每个 D-Bus read 都有 deadline，避免一个无响应播放器阻塞整个 poll loop。 | 外部 call 结果区分 timeout、error、empty；poll supervisor 保证单次 sample 不阻塞其他 player。 | `infrastructure/mpris` + `application/playback` |
| `#62` | LRC 行数上限，避免 2 MB tag 物化十几万行；同一 PR 还修了 restart 失败不能退出当前实例。 | parser 预算和应用 restart result 是两个独立契约，不能继续捆在同一 PR/协调器里；行数上限导致 `Rejected` 而非静默截断。 | parser boundary；restart 属于 application lifecycle |
| `#63` | 处理六类“用户只看到没歌词但没有失败”的情况：NetEase 错误 cookie、Cider build 永挂、WS CONNECTING 永不结束、send buffer 无上限、循环 nowPlaying、负 miss 缓存。 | transport 必须有 state machine、generation、open/request/body/buffer budgets；“HTTP 200”不等于“结果属于本请求”。 | TS `CiderTransport` + Python `Receiver` + `SourceResult` |
| `#64` | 统一修复 MPRIS bridge 把 queue cumulative length/position 当歌曲值、玩家选错、title grammar、version matching、query variant、miss reason；Overlay 同时增加 interlude 和 font fit。 | 播放器观察、稳定身份、候选请求、匹配证据、展示状态必须是连续但独立的阶段；不能由 MPRIS poll 直接改歌词和 HUD。展示解析状态使用 `NoTrack/Resolving/LyricsAvailable/LyricsNotFound`。 | `application/playback` -> `domain/matching` -> `application/lyrics` -> `domain/display` |

## Phase 0 决策登记

`Retain` 表示用户可见能力继续存在，`Redefine` 表示能力保留但公共契约改变，`Remove` 表示不再
承诺该行为。本矩阵目前没有需要 `Remove` 的用户能力；每个条目的最后一列给出已有测试入口或待补
的 corpus 入口。

| PR | 决策 | 公共输入、输出和失败语义 | Owner / test entry |
| --- | --- | --- | --- |
| `#26` | Retain | 保留 raw artist/title、清洗视图和恢复 artist 三个结果；没有分隔证据时恢复失败并保留原 artist。 | `track_identity`；`tests/test_titles.py`、`tests/test_mpris.py` |
| `#32` | Redefine | 精确 song id 只是优化；命中后仍验证歌词，失败、禁用或无 timed lines 时继续自动来源。 | `lyrics_workflow`；`tests/test_lyrics_resolver.py` |
| `#33` | Retain | `MatchEvidence`、confidence 和 ranking score 分开；版本冲突或低置信度不能仅靠分数接受。 | `lyrics/matching`；`tests/test_lyrics.py` |
| `#34` | Retain | 合法 file path 的 sidecar 优先；缺失、空、无 timed lines 或越界路径是 `Miss`，不是异常。 | `local_lyrics`；`tests/test_lyrics_local.py` |
| `#36` | Retain | sidecar > embedded；可选 mutagen 不可用与 tag miss 分开；普通文本不能成为可展示歌词。 | `local_lyrics`；`tests/test_lyrics_local.py` |
| `#37` | Retain | 支持的 provider song id 生成可信 hint；未知或 malformed hint 不进入请求。 | `provider_hint`；`tests/test_lyrics_hint.py`、`tests/test_lyrics_resolver.py` |
| `#39` | Retain | 播放器选择由一个 typed policy 同时服务 runtime/settings，UI 只接收 DTO。 | `playback_selection`；`tests/test_player_selection.py`、`tests/test_settings_dialog.py` |
| `#40` | Retain | KRC word timing 保留；不完整 word timing 回退 line timing，解析预算或格式错误明确拒绝。 | `lyric_document`；`tests/test_lyrics_krc.py`、`tests/test_lyric_formats.py` |
| `#42` | Retain | non-song gate 使用 raw reported title；normalized title 不能覆盖 gate 证据。 | `track_identity/source_gate`；`tests/test_mpris.py` |
| `#45` | Retain | 配置保存失败保留旧配置，损坏输入隔离并可观测；解析和持久化不把 raw JSON 交给业务层。 | `config_store`；`tests/test_config.py` |
| `#49` | Retain | HTTP body、JSON、解压 payload 都受明确上限；HTTP 200、超限或错误 payload 分别产生 typed result。 | `http_payload`；`tests/test_lyrics_providers.py`、`tests/test_lyrics_krc.py` |
| `#50` | Retain | 先验证 regular file 再读取；worker 有 owner、预算和 shutdown 语义，取消 wrapper 不伪称取消底层读取。 | `local_lyrics/task_owner`；`tests/test_lyrics_local.py`、`tests/test_lyrics_resolver.py` |
| `#51` | Retain | version marker 只从标题末尾识别；版本冲突是 `Rejected`，不能静默删除 qualifier。 | `title_grammar`；`tests/test_titles.py`、`tests/test_lyrics.py` |
| `#56` | Retain | line/word 时间必须非负、有序且不超过合法范围；不合法输入拒绝或丢弃对应 line，并保留原因。 | `lyric_document`；`tests/test_lyrics_krc.py`、`tests/test_lyric_formats.py` |
| `#57` | Retain | 相同请求共享任务；caller cancel 不取消其他 caller，owner shutdown 才取消 shared work。 | `lyrics_resolution`；`tests/test_lyrics_resolver.py` |
| `#58` | Retain | translation merge 保持 canonical 文档结果，索引优化不能改变 nearest-time 和 tolerance 语义。 | `translation_merge`；`tests/test_lyric_formats.py` |
| `#59` | Redefine | Cider clock 与歌词来源解耦为可配置 policy：可跟随歌词来源，或优先匹配的 Cider tick；不可用时回退 MPRIS。 | `clock_coordinator`；`tests/test_clock.py`、`tests/test_receiver.py` |
| `#61` | Retain | 每次 D-Bus read 有 deadline；timeout、error、empty metadata 不阻塞其他 player，也不伪装成功。 | `mpris_adapter/playback`；`tests/test_mpris_session.py`、`tests/test_mpris.py` |
| `#62` | Redefine | LRC 行数上限保留，但超限是明确 `Rejected` 而非静默截断；restart failure 单独登记。 | `lrc_parser` / lifecycle；`tests/test_lyric_formats.py`、`BehaviorCase` |
| `#63` | Retain | Cider transport 保留 generation、open/request/body/buffer budgets；迟到或不属于当前请求的结果丢弃。 | `cider_transport/receiver`；`tests/test_receiver.py`、plugin tests |
| `#64` | Redefine | 播放观察、identity、resolution、clock 和 display 分阶段发布；状态使用 `NoTrack/Resolving/LyricsAvailable/LyricsNotFound`。 | application workflow；`tests/test_mpris_provider.py`、`tests/test_select.py`、display corpus |

### 已确认的来源和展示 policy

- 来源顺序为“用户确认歌词、sidecar、embedded、精确 provider song id、当前选中的 Cider 会话、配置的网络来源”。
- 自动 cache 只加速所属来源，不改变顺序；用户确认的结果才成为最高优先级的本地歌词。
- `ordered_first` 默认启用，`best_confidence` 是显式可选 policy。
- `EXACT/HIGH` 可以直接作为自动结果；`MEDIUM` 等待其他来源后只作为 fallback，不自动持久化。
- Cider 断线时，已经找到的歌词不清空，时钟回退到 MPRIS；Position 暂不可读时保留歌词和最后已知位置。
- 短暂空 metadata 继续由 stabilizer 的 settling window 处理；稳定确认无曲目后才进入 `NoTrack`。
- 旧 generation 的迟到结果不得更新当前曲目的 display/state；Phase 0 不引入缓存 TTL。

## 新设计的决策分组

### 已确认的目标行为

- 精确 provider song id 能绕过不必要的 title search，失败后仍 fallback。
- 同音频 sidecar 优先于 embedded/network；没有 timed lines 的文本不能进入 HUD。
- provider order 是用户可见策略；cache 不能凭空成为独立 provider。
- 版本冲突、instrumental、live 等错误 recording 不能因高相似度被接受。
- 一个 Cider client 的 snapshot/tick 不会无条件抢回时钟；是否使用由 clock policy 决定。
- 过期 generation 的 provider 结果不能覆盖新曲目。

### 必须在新设计中明确

### Phase 0 记录的失败路径

- `SourcePlan` 统一生成完整 precedence；resolver 不再自行选择并发或顺序。
- `MEDIUM` 不在搜索尚未结束时截断后续来源；无更可靠结果时才显示，并允许用户确认保存。
- Cider 断线或 Position 不可用不等于 `LyricsNotFound`；已找到的歌词保留，clock 使用 fallback。
- 短暂空 metadata 不清除已提交曲目；稳定窗口确认无曲目后才发布 `NoTrack`。

## 当前边界错误的共同形状

这些 PR 不是互相独立的 case。它们反复跨过同一条错误边界：

```text
外部 raw value -> 直接清洗/转换 -> 协调器分支 -> 直接写 state/HUD
```

目标应改成：

```text
外部 adapter -> typed observation/result -> domain policy -> application workflow -> view model -> presentation
```

任何新 provider、播放器或 parser 都只能实现 adapter/port，不得直接增加 MPRIS poll、Overlay widget 或
全局 state 的条件分支。
