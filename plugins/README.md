# External adapter protocol

[中文](README.zh-CN.md)

`plugins/` is the extension point for external player adapters. Kotonoha does
not ship a player-specific plugin here. An adapter can be written in any
language and only needs to publish normalized playback facts and a complete
timed lyric document over the generic WebSocket protocol.

## Connection

Connect to the local receiver:

```text
ws://127.0.0.1:28745/kotonoha/adapter
```

The port is `28745` by default and can be overridden with Kotonoha's `--port`
option. The receiver listens on the loopback interface. It accepts JSON text
frames and keeps the connection open for the lifetime of the adapter.

The current receiver does not send application-level acknowledgements or
`resync` commands. After a disconnect, reconnect and send a fresh `snapshot`.
The HTTP `POST` route at the same path is only a local debug/integration route;
WebSocket is the adapter contract.

## Message envelope

Every message uses this envelope:

| Field | Type | Meaning |
| --- | --- | --- |
| `protocol` | string | Must be `kotonoha.adapter`. |
| `version` | integer | Must be `1`. |
| `type` | string | `snapshot` or `clock`. |
| `adapter` | string | Stable id of the external player adapter, not the lyric provider. |
| `sequence` | integer | Non-negative sequence number for this connection. |
| `capturedAt` | string | Non-empty producer timestamp, normally an ISO 8601 string. |

Sequences are checked per connection across both message types. A message with
a sequence number less than or equal to the last accepted message is discarded.
When an adapter reconnects, it may start a new sequence space.

## Snapshot

Send a complete snapshot when the connection opens, when the track changes, or
when the lyric document changes. `lyrics` may be `null` when the player has no
lyrics yet.

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

`playback` is required for a snapshot. Its `playerId` and `status` are
required. `positionS`, `durationS`, and `track` may be `null`; when `track` is
present, `stableId`, `url`, and the track duration are optional, while title,
raw title, artist, and album are strings.

The `lyrics` object represents the final lyric artifact, not the player that
transported it:

- `source` is a required, stable provider id such as `lrclib`, `netease`, or
  `apple-music`.
- `sourceName` is an optional human-readable label such as `LRCLIB` or
  `Apple Music`.
- `timing` is `Line` or `Word` when `lines` is non-empty.
- `lines` are ordered and each line has non-negative `start` and `end` values.
- Each word either has both non-negative `start` and `end` values, or both are
  `null`.
- `title`, `artist`, `album`, and `durationS` are optional. Missing values are
  filled from the playback track where possible.

The adapter must send the complete document. It must not send display-derived
fields such as `currentLine`, `previousLine`, `nextLine`, `aroundLines`, or
interlude state. Kotonoha's display engine selects the current line, context,
interlude, and word progress consistently for every adapter.

## Clock

Send a lightweight clock update for position and playback-state calibration.
It is not necessary to send one for every display frame because Kotonoha
interpolates between accepted observations using its local monotonic clock.
Send updates at a stable low frequency, and send one immediately after a seek
or playback-state change.

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

`trackRef` must identify the track from the latest accepted snapshot. When a
snapshot has a `stableId`, Kotonoha forms it as
`adapter:playerId:stableId`. A clock for a different track is rejected and does
not replace the current display. `positionS` may be `null` when the position is
temporarily unavailable. `status` is one of `Playing`, `Paused`, `Stopped`, or
`Unknown`.

## Protocol adaptation boundary

An adapter owns all player-specific and third-party details. Its boundary work
should follow this sequence:

1. Read the player API, browser store, or other external source.
2. Normalize player identity, track metadata, playback status, position, and
   duration into the `playback` shape.
3. Fetch or parse lyrics and normalize them into the complete `lyrics` shape.
4. Put the final lyric provider in `lyrics.source`; put only its display label
   in `lyrics.sourceName`.
5. Publish a `snapshot` for track/document changes and `clock` for position
   calibration.

Keep these identities separate:

| Identity | Example | Owner |
| --- | --- | --- |
| Transport adapter | `example-player` | External integration |
| Player instance | `example-window` | External player |
| Track identity | `track-123` | Player or catalog |
| Lyric provider | `lrclib` | Lyric source that produced the document |

The adapter should reconnect with backoff, resend a full snapshot after
connecting, and stop sending when its player data is no longer valid. It should
never silently turn a malformed or partial lyric response into a valid
snapshot; invalid data is better omitted until a complete document is ready.
