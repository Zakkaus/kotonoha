# 外部适配器协议

[English](README.md)

`plugins/` 是外部播放器适配器的扩展入口。Kotonoha 不在这里捆绑任何
播放器专用插件。适配器可以使用任意语言实现，只需要通过通用 WebSocket
协议发布规范化的播放事实和完整的带时间轴歌词文档。

应用内的歌词解析、来源优先级、cache 和手动选词不属于本协议；请参阅
[`docs/SPEC-lyrics.md`](../docs/SPEC-lyrics.md)。

## 连接

连接到本地接收端：

```text
ws://127.0.0.1:28745/kotonoha/adapter
```

默认端口是 `28745`，可以通过 Kotonoha 的 `--port` 选项覆盖。接收端监听
loopback 网卡，只接受 JSON 文本帧，并在适配器运行期间保持连接。

当前接收端不会发送应用层确认消息，也不会发送 `resync` 命令。连接断开后，
适配器应重新连接并发送一份新的 `snapshot`。同一路径上的 HTTP `POST` 仅用于
本地调试或集成测试；适配器正式协议是 WebSocket。

## 消息信封

每条消息都使用以下信封：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `protocol` | string | 必须是 `kotonoha.adapter`。 |
| `version` | integer | 必须是 `1`。 |
| `type` | string | `snapshot` 或 `clock`。 |
| `adapter` | string | 外部播放器适配器的稳定 id，不是歌词 provider。 |
| `sequence` | integer | 当前连接内的非负序号。 |
| `capturedAt` | string | 非空的生产端时间戳，通常使用 ISO 8601。 |

接收端会在同一连接内跨两种消息检查序号。小于或等于上一条已接受消息的
序号会被丢弃。适配器重新连接后可以重新开始一个序号空间。

## Snapshot

连接建立、歌曲切换或歌词文档变化时发送完整的 snapshot。如果播放器暂时没有
歌词，`lyrics` 可以是 `null`。

```json
{
  "protocol": "kotonoha.adapter",
  "version": 1,
  "type": "snapshot",
  "adapter": "example-player",
  "sequence": 1,
  "capturedAt": "2026-08-29T12:00:00Z",
  "playback": {
    "playerId": "example-window",
    "status": "Playing",
    "positionS": 12.5,
    "durationS": 192.0,
    "track": {
      "stableId": "track-123",
      "title": "Song Title",
      "rawTitle": "Song Title",
      "artist": "Artist",
      "album": "Album",
      "url": "https://example.invalid/track-123",
      "durationS": 192.0
    }
  },
  "lyrics": {
    "source": "lrclib",
    "sourceName": "LRCLIB",
    "songId": "track-123",
    "timing": "Line",
    "language": "en",
    "title": "Song Title",
    "artist": "Artist",
    "album": "Album",
    "durationS": 192.0,
    "lines": [
      {
        "index": 0,
        "id": "line-0",
        "start": 0.0,
        "end": 3.2,
        "text": "First line",
        "translation": "",
        "words": []
      }
    ]
  }
}
```

snapshot 必须包含 `playback`，其中 `playerId` 和 `status` 必填。
`positionS`、`durationS` 和 `track` 可以是 `null`。`track` 存在时，
`stableId`、`url` 和歌曲时长可选；标题、原始标题、艺术家和专辑必须是字符串。

`lyrics` 表示最终的歌词产物，而不是传输它的播放器：

- `source` 是必填的稳定 provider id，例如 `lrclib`、`netease` 或
  `apple-music`。
- `sourceName` 是可选的人类可读名称，例如 `LRCLIB` 或 `Apple Music`。
- 当 `lines` 非空时，`timing` 必须是 `Line` 或 `Word`。
- `lines` 必须有序，每行的 `start` 和 `end` 都必须是非负数。
- 每个单词要么同时具有非负的 `start` 和 `end`，要么两者都是 `null`。
- `title`、`artist`、`album` 和 `durationS` 可选。缺失时接收端会尽量从
  playback track 补齐。

适配器必须发送完整歌词文档，不能发送 `currentLine`、`previousLine`、
`nextLine`、`aroundLines` 或 interlude 状态等展示层字段。当前行、上下文行、
interlude 和逐字进度都由 Kotonoha 的显示引擎统一计算，确保不同适配器行为一致。

## Clock

发送轻量的 clock 更新，用于校准播放位置和播放状态。由于 Kotonoha 会使用本地
单调时钟在已接受的观测值之间插值，因此不需要为每一帧显示都发送消息。适配器应
以稳定的低频率发送 clock，并在 seek 或播放状态变化后立即发送一次。

```json
{
  "protocol": "kotonoha.adapter",
  "version": 1,
  "type": "clock",
  "adapter": "example-player",
  "sequence": 2,
  "capturedAt": "2026-08-29T12:00:01Z",
  "trackRef": "example-player:example-window:track-123",
  "positionS": 13.5,
  "status": "Playing"
}
```

`trackRef` 必须对应最近一次已接受 snapshot 中的歌曲。如果 snapshot 带有
`stableId`，Kotonoha 会按 `adapter:playerId:stableId` 生成它。指向其他歌曲的
clock 会被拒绝，不会替换当前展示。`positionS` 在播放位置暂时不可用时可以是
`null`。`status` 可以是 `Playing`、`Paused`、`Stopped` 或 `Unknown`。

## 协议适配边界

适配器负责处理所有播放器和第三方服务的细节。边界处理应遵循以下顺序：

1. 读取播放器 API、浏览器 store 或其他外部数据源。
2. 将播放器身份、歌曲元数据、播放状态、位置和时长规范化为 `playback` 结构。
3. 获取或解析歌词，并规范化为完整的 `lyrics` 结构。
4. 将最终歌词 provider 放入 `lyrics.source`，只将其展示名称放入
   `lyrics.sourceName`。
5. 歌曲或歌词文档变化时发布 `snapshot`，播放位置变化时发布 `clock` 做校准。

以下身份必须分开：

| 身份 | 示例 | 所有者 |
| --- | --- | --- |
| 传输适配器 | `example-player` | 外部集成 |
| 播放器实例 | `example-window` | 外部播放器 |
| 歌曲身份 | `track-123` | 播放器或 catalog |
| 歌词 provider | `lrclib` | 生成该歌词文档的歌词来源 |

适配器应带退避策略重连，连接后重新发送完整 snapshot；当播放器数据失效时，
应停止发送。不要把格式错误或不完整的歌词响应静默转换成有效 snapshot；在完整
文档准备好之前暂时不发送，比发布一个看似有效的半成品更安全。
