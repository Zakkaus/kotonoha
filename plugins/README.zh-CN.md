# 外部适配器协议

[English](README.md)

本文定义外部播放器适配器与 Kotonoha 之间的本地协议。适配器可以使用任意语言实现，职责是向 Kotonoha 发布规范化播放事实和完整的带时间轴歌词文档。

歌词解析、来源优先级、缓存和手动选词属于应用层，不属于本协议。相关规则见 [`docs/SPEC-lyrics.zh-CN.md`](../docs/SPEC-lyrics.zh-CN.md)。

## 端点

| 属性 | 值 |
| --- | --- |
| WebSocket | `ws://127.0.0.1:28745/kotonoha/adapter` |
| 默认端口 | `28745` |
| 覆盖方式 | Kotonoha `--port` 选项 |
| 监听地址 | Loopback（`127.0.0.1`） |
| 载荷 | UTF-8 JSON 文本帧 |

接收端在适配器运行期间保持 WebSocket 连接。同一路径也接受 HTTP `POST`，仅用于本地调试和集成测试；适配器正式协议是 WebSocket。

接收端不会发送应用层确认消息或 `resync` 命令。重新连接后，适配器发送完整的 `snapshot`，并为该连接重新开始序号空间。

## 消息信封

每条消息都包含以下字段：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `protocol` | string | `kotonoha.adapter` |
| `version` | integer | `1` |
| `type` | string | `snapshot` 或 `clock` |
| `adapter` | string | 外部适配器稳定 id，不是歌词 provider id |
| `sequence` | integer | 当前连接内的非负序号 |
| `capturedAt` | string | 非空的生产端时间戳，通常使用 ISO 8601 |

同一连接内的两种消息共享序号顺序。序号小于或等于上一条已接受消息的消息会被丢弃。

## Snapshot

Snapshot 是一首歌及其歌词文档的完整状态。连接建立、歌曲切换或歌词文档变化时发送。暂时没有歌词时，`lyrics` 可以是 `null`。

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

### Playback 对象

`playback` 必填，`playerId` 和 `status` 必填。`positionS`、`durationS` 和 `track` 可以是 `null`。

`track` 存在时，`title`、`rawTitle`、`artist` 和 `album` 必须是字符串。`stableId`、`url` 和歌曲时长可选。歌词缺失的元数据会在可能时从歌曲信息补齐。

`status` 的值为 `Playing`、`Paused`、`Stopped` 或 `Unknown`。

### Lyrics 对象

`lyrics` 描述最终歌词产物，不描述传输它的播放器或适配器。

- `source` 是稳定的 provider id，例如 `lrclib`、`netease` 或 `apple-music`。
- `sourceName` 是可选的人类可读 provider 名称。
- 当 `lines` 非空时，`timing` 为 `Line` 或 `Word`。
- `lines` 必须有序，每行的 `start` 和 `end` 都是非负数。
- 每个单词要么同时具有非负的 `start` 和 `end`，要么两者都是 `null`。
- `title`、`artist`、`album` 和 `durationS` 可选。

文档只包含来源数据。`currentLine`、`previousLine`、`nextLine`、`aroundLines` 和 interlude 状态等展示派生字段由 Kotonoha 的 display engine 计算。

## Clock

Clock 更新最近一次 snapshot 的播放位置和状态，用于媒体时钟校准。Kotonoha 会在已接受的观测值之间插值，不要求每个显示帧都发送消息。seek 或播放状态变化后发送一次，正常播放时以稳定的低频率发送。

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

`trackRef` 将 clock 绑定到最近一次已接受的 snapshot。如果 snapshot 带有 `stableId`，Kotonoha 按 `adapter:playerId:stableId` 生成该引用。指向其他歌曲的 clock 会被拒绝，不会替换当前展示。播放位置暂时不可用时，`positionS` 可以是 `null`。

## 适配边界

适配器负责播放器 API、浏览器数据、第三方载荷及其规范化。边界只向 Kotonoha 产出协议定义的结构：

1. 读取播放器状态和歌曲元数据。
2. 将播放器身份、歌曲元数据、状态、位置和时长规范化为 `playback`。
3. 将歌词获取或解析为一个完整的 `lyrics` 文档。
4. 将歌词 provider id 写入 `lyrics.source`，将展示名称写入 `lyrics.sourceName`。
5. 歌曲或文档变化时发布 `snapshot`，播放位置变化时发布 `clock`。

以下身份必须分开：

| 身份 | 示例 | 所有者 |
| --- | --- | --- |
| 传输适配器 | `example-player` | 外部集成 |
| 播放器实例 | `example-window` | 外部播放器 |
| 歌曲身份 | `track-123` | 播放器或 catalog |
| 歌词 provider | `lrclib` | 生成该文档的歌词来源 |

## 重连和无效数据

适配器应带退避策略重连，每次连接后重新发送完整 snapshot。播放器数据失效时停止发布。格式错误或不完整的歌词数据不能被转换成有效 snapshot；在完整且通过校验的文档准备好之前，省略歌词文档。
