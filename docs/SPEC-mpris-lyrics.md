# Kotonoha MPRIS + 外部歌词源设计规格

本文描述当前实现。目标是在不改动 HUD 渲染、Qt bridge、时钟与卡拉 OK 组件的前提下，让任意 MPRIS 播放器可靠地使用外部定时歌词，并让 Cider 公共 HTTP API 作为可排序的实时歌词来源参与同一条解析链。外部播放器统一使用版本化的 `kotonoha.adapter` v1 入口，不再保留 Cider 专用旧路由。

## 1. 关键原则

- 当前播放器和歌词来源是两个独立选择。即使当前播放器是 Cider，也优先按用户配置尝试网易云、lrclib 或其他外部 provider。
- Cider 不是固定 fallback，也不因当前播放器身份自动优先；它在 `lyrics_sources` 中出现在哪里，就在哪里尝试。
- Cider HTTP 一次返回当前歌曲的完整带时间歌词文档；播放位置约每秒校准一次，两次校准之间由本地 MediaClock 推进。
- Cider 是播放器/传输适配器，不是最终歌词来源；Cider 响应中的 source.provider 会在边界层归一化为 source_id，并保留 source_name。
- 本地缓存属于每一个网络 provider 的内部阶段，不是单独的 provider。
- 不保存 MPRIS player、track ID、搜索词到 provider 歌曲的持久映射。
- `overlay.py`、`karaoke_label.py`、`karaoke.py`、`native.py` 和 layer-shell bridge 保持既有视觉/平台行为；外部插件使用 `kotonoha.adapter` v1。

## 2. 数据流

```text
MPRIS Metadata/Status/Position
            |
            v
  TrackStabilizer (忽略空值，等待稳定组合)
            |
            v
  MprisPlaybackCoordinator -> PlaybackSample
            |
  MprisLyricsCoordinator -> MprisResolutionSession
            |                         |
            |                  LyricsResolutionWorkflow
            |                         |
            |                  LyricsResolver (source policy)
            |                    /          \
            |                   /            \
  MprisDisplayBinding    provider local/network    CiderApiProvider
            |                   \            /          |
            +--------------------+----------+           |
                                 v                      |
                         DisplayCoordinator <-----------+
                                 |
                         DisplayEngine -> DisplayFrame
                                 |
                  QtDisplayPublisher -> LyricsState -> Overlay

  AdapterReceiver -> AdapterProtocolDecoder -> SourceOwnershipCoordinator
```

MPRIS 负责当前歌曲身份和外部歌词的进度。Cider 被选中时，内容由同一首歌的一次 HTTP 歌词请求提供，播放位置由 Cider HTTP 的低频校准驱动，MediaClock 负责帧间插值，避免两个时钟同时驱动 HUD。

## 3. Provider 顺序

假设用户配置：

```text
netease -> lrclib -> cider
```

启用缓存时的实际尝试顺序必须是：

1. 本地网易云缓存
2. 网络网易云
3. 本地 lrclib 缓存
4. 网络 lrclib
5. 当前可匹配的 Cider 实时快照

如果调整为 `lrclib -> cider -> netease`，顺序相应变为：本地 lrclib、网络 lrclib、Cider、本地网易云、网络网易云。缓存开关关闭时只跳过网络 provider 的缓存读写，不改变 provider 顺序。

网络 provider 正常返回无结果时记录 30 秒内存 miss，减少切歌抖动造成的重复请求。网络异常不记录 miss。相同歌曲、相同来源顺序的并发请求共用一个 in-flight task。

## 4. 搜索归一化与置信度

归一化使用 Unicode NFKC 和 `casefold()`，安全处理 `feat.`/`ft.` 边界、艺术家分隔符和标题括号。`Live`、`Remix`、`Remaster`、`Acoustic` 等版本标签单独提取，不能因为去掉括号而把不同版本当成同一首歌。

高置信度的直观含义：

- 标题相同或非常接近；
- 艺术家、专辑或接近的时长至少提供一项独立身份依据；
- 已知时长差不超过约 3 秒；
- 没有明确版本冲突。

中置信度可用于当前会话，例如标题精确但播放器暂时缺 artist/duration；它不能写入文件缓存。只有时长接近、标题和艺术家不一致的候选不是匹配。

查询先使用播放器原始 `title + artist`，必要时再使用基础标题和主艺术家。第一轮只有中置信度候选时继续归一化查询，争取高置信度结果。

## 5. Provider artifact 与文件缓存

网易云和 lrclib 网络层返回统一的 `LyricsArtifact`：

- provider 名称；
- provider 稳定歌曲 ID；
- provider 返回的 title/artist/album/duration；
- 原始歌词 payload；
- 已解析的 `LyricLine`；
- 本次匹配置信度。

SQLite 主键为：

```text
(provider, provider_song_id)
```

数据库不包含 player、MPRIS track ID、原始 query、search key 或 alias 表。播放时只扫描当前 provider 的缓存 artifact，用当前 MPRIS 元数据重新执行同一套匹配逻辑。这样播放器、MPRIS bridge 或查询写法改变时不需要维护额外映射。

缓存默认位于：

```text
$XDG_CACHE_HOME/kotonoha/lyrics.sqlite3
```

只持久化高置信度 artifact，默认保留最近使用的 1000 条。JSON 或歌词 payload 损坏时删除该条目，并继续同一 provider 的网络阶段。设置页可禁用或清空缓存。

## 6. Provider 细节

### 网易云

- 搜索结果先经过统一匹配，不再由时长单独决定。
- 优先解析 YRC；YRC 字段存在但解析不到有效行时回退 LRC。
- `tlyric` 按时间合并为翻译。
- provider 稳定歌曲 ID 和原始 YRC/LRC/tlyric 一起进入 artifact。

### lrclib

- `/api/get` 精确请求失败或结果不可信时继续 `/api/search`。
- 搜索结果整体匹配排序，不再直接选择第一条带 `syncedLyrics` 的记录。
- 保存 lrclib record ID 和原始 `syncedLyrics`。

### Cider HTTP API

- CiderApiClient 通过 Cider 的公开 HTTP API 读取 playback 和 lyrics；token 可选，空 token 不发送 apptoken。
- /api/v2/playback 约每秒读取一次，作为 MediaClock 的校准样本；显示帧之间不请求 Cider。
- 切歌后只请求一次 /api/v2/lyrics/current?words=true，当前响应不是目标歌曲时回退到 /api/v2/lyrics/:id。
- source.provider 是最终歌词来源，例如 Apple Music 或其他 provider；它不被改写成 Cider。
- HTTP 断开或歌词不存在时保留 MPRIS 的候选/回退行为；外部播放器如需推送，使用通用 adapter v1 的 `snapshot` / `clock` 消息。
- WebSocket adapter 断开时丢弃其 candidate；若该连接仍拥有展示，会发布 `NoTrack` 清除浮窗，
  而不会覆盖已经由 MPRIS 接管的展示。

## 7. MPRIS 切歌稳定化

`PropertiesChanged` 只唤醒采样，不直接发起歌词请求。每次采样：

1. 读取 PlaybackStatus 和 Metadata；
2. 尝试读取 Position，失败时保留 Metadata 路径；
3. 再读一次 Metadata；
4. 两次身份字段不同则丢弃本次样本；
5. 相同组合保持稳定后才提交新的 track generation。

title 和 artist 都为空的 `""/""` 样本永不提交，也不会搜索、写 miss 或写缓存。完整元数据稳定约 350 ms 后提交；缺 artist 时等待约 800 ms。新 generation 立即取消旧歌词请求，任何异步返回在写状态前再次检查 generation。

当前 Playing player 短暂推空元数据时保留旧内容并等待恢复；播放器消失或停止约 350 ms 后才清空状态。Paused 且元数据有效的播放器仍可保留歌词。Position 不可用不会阻止歌词获取，只是不产生新的 MPRIS 进度校准。

## 8. 模块

```text
src/kotonoha/providers/mpris_track.py      元数据解析、Observation、稳定器
src/kotonoha/providers/mpris_playback.py   MPRIS session、订阅、poll 和稳定化生命周期
src/kotonoha/providers/mpris_resolution.py MPRIS 歌词解析会话与 resolver 生命周期
src/kotonoha/providers/mpris_display.py    MPRIS sample 到 display/timeline 的绑定
src/kotonoha/providers/mpris.py            MPRIS facade 与配置转发
src/kotonoha/providers/mpris_lyrics.py     MPRIS lyric generation、ownership 与 workflow 编排
src/kotonoha/providers/cider_client.py    Cider HTTP session、响应边界和可选 token
src/kotonoha/providers/cider_api.py       Cider 低频校准、按 track generation 的歌词任务
src/kotonoha/lyrics/ownership.py       live source facts 与 source 绑定
src/kotonoha/lyrics/match.py           归一化、版本冲突、置信度
src/kotonoha/lyrics/artifact.py        provider-neutral artifact
src/kotonoha/lyrics/cache.py           provider-scoped SQLite 缓存
src/kotonoha/lyrics/sources.py         local/exact/network source contracts
src/kotonoha/lyrics/resolver.py        source policy、缓存与 in-flight 去重
src/kotonoha/lyrics/netease.py         网易云搜索与 YRC/LRC 解析
src/kotonoha/lyrics/lrclib.py          lrclib exact/search 与排序
```

所有网络与磁盘 I/O 保持异步边界；SQLite 操作通过工作线程执行。Qt widget 与 layer-shell 操作仍只在 UI 线程发生。
