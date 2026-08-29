# 歌词、cache 和手动选词

本文记录当前歌词 feature 的模型、来源解析、SQLite cache 和手动选词行为。

## 核心模型

- `TrackIdentity` 和 `PlaybackObservation` 是各播放适配器输出的规范化播放事实。
- `TrackMetadata` 是歌词匹配和搜索使用的 provider-neutral metadata。
- `LyricsArtifact` 保存 provider identity、原始 payload、解析后的完整歌词和匹配度。
- `LyricsDocument` 是完整时间轴；显示层从它计算当前行、上下文、逐字进度和 interlude。
- `LyricsSourceResult` 携带 `source_id`、document、匹配度、时长、cache artifact 和 source kind。

## 来源和解析

| 类型 | 来源 | 能力 |
| --- | --- | --- |
| `local` | sidecar、embedded | 只处理播放器提供的 exact hint |
| `network` | Netease、QQ Music、LRCLIB、Kugou | metadata 搜索或 song id 精确获取 |
| `live` | Cider HTTP、generic adapter | 提供当前播放候选 |

默认歌词来源顺序为：

```text
netease -> lrclib -> kugou -> cider
```

`lyrics_sources` 控制歌词 provider；`display_sources`（默认
`mpris -> cider -> adapter`）控制播放事实/live candidate。两者互不替代。
QQ Music 目前只支持 exact song id，Cider 只提供当前播放器轨道；它们没有
metadata manual-search capability，搜索界面会返回具体 unavailable reason。

每个稳定 MPRIS track 有独立 generation。旧 generation 的 task 会被取消，过期
结果不能更新当前显示。自动解析优先级为：

1. exact hint 路径先查匹配的 `MANUAL` cache，再查 hint 指定的 source；
2. 普通 source plan 先查匹配当前 track 的 `MANUAL` cache；
3. `prefer_best_lyrics` 开启时按匹配度竞争候选，配置顺序只打破平局；关闭时按配置顺序遇到第一个有效结果即停止；
4. 普通 cache 只作为所属 provider 的 automatic cache 命中；网络异常不伪装成 miss。

## SQLite cache

`LyricsCache` 是异步 facade，`LyricsCacheStorage` 通过注入的 worker 执行同步
SQLite。默认路径是 `$XDG_CACHE_HOME/kotonoha/lyrics.sqlite3`，schema version
为 `1`，默认最多保留 `1000` 条，按 `last_accessed` 淘汰。记录 key 为
`(provider, provider_song_id)`，保存 provider metadata、payload、时间、mode 和
版本信息；损坏或没有 timed lines 的 payload 会被删除并视为 miss。

| mode | 含义 |
| --- | --- |
| `AUTO` | 普通解析仅在高置信度时写入，只服务所属 provider 的自动命中 |
| `MANUAL` | 用户确认的结果，跨普通解析和 exact hint 优先匹配当前 track |

公开操作：

- `search(query)`：按标题、艺术家、专辑、provider 或 song id 模糊搜索，返回多个条目并按最近使用排序；
- `get(key)`、`count()`：读取单条 metadata 或总数；
- `upsert(artifact, mode)`、`update(key, artifact, mode)`：创建/替换或更新已有记录；`update()` 保留给歌词 workflow，不是管理页面编辑入口；
- `delete(key)`、`delete_many(keys)`、`clear()`：删除指定条目、批量删除或清空；
- `lookup()`、`lookup_manual()`：resolver 专用的内容命中。

缓存管理页面只使用 metadata search 和 delete/clear。它与 resolver 共享同一
`LyricsCache`，但通过窄的 management/write port 接入，不依赖完整 MPRIS facade。

## 手动搜索和应用

Overlay 的查找按钮打开当前歌曲的 modeless 搜索窗口。标题、艺术家和专辑预填
且可编辑，当前时长只读展示。搜索服务并发查询已选 provider：每个 provider 最多
`30` 个候选，一次最多向 UI 暴露 `90` 个；按 `provider:provider_song_id` 去重。
列表显示来源、标题、艺术家、专辑、时长、歌词格式、翻译可用性和匹配度。候选
保留完整 artifact；不可用 provider 以带 `source/reason` 的 typed result 返回。

应用候选时：

1. 以 `MANUAL` mode 写入共享 cache；
2. 调用 `DisplayCoordinator.apply_manual_artifact()`；
3. 仅当当前播放 track 仍匹配搜索 track 时替换 document；
4. 立即按当前播放位置重新投影，播放中无需等待下一首；
5. 刷新搜索窗口的来源状态。

状态显示四个独立事实：当前歌词 provider、获取方式、播放事实来源
（MPRIS/Cider/adapter）和 cache 状态（未使用/自动 cache/手动选择）。切歌后手动
document 不覆盖新 track，新 track 按当前 source policy 重新解析。

## 本地来源和失败

sidecar 和 embedded 在 local worker 中读取，不写入 network cache，origin 分别为
`sidecar` 和 `embedded`。provider 的 transport、解析和 payload 错误在边界处转换
为窄 exception 或 typed unavailable result；cache 失败必须报告
`LyricsCacheError`，不能返回虚假成功。
