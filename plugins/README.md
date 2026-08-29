# External Adapter Protocol

[中文](README.zh-CN.md)

This document defines the local protocol for external player adapters. An
adapter may be implemented in any language. Its responsibility is to publish
normalized playback facts and complete timed lyric documents to Kotonoha.

Lyric resolution, source priority, caching, and manual selection belong to the
application and are outside this protocol. See
[`docs/SPEC-lyrics.md`](../docs/SPEC-lyrics.md) for those rules.

## Endpoint

| Property | Value |
| --- | --- |
| WebSocket | `ws://127.0.0.1:28745/kotonoha/adapter` |
| Default port | `28745` |
| Override | Kotonoha `--port` option |
| Bind address | Loopback (`127.0.0.1`) |
| Payload | UTF-8 JSON text frames |

The receiver keeps a WebSocket open for the adapter lifetime. The same path
also accepts HTTP `POST` for local debugging and integration tests; WebSocket
is the adapter contract.

The receiver sends no application-level acknowledgements or `resync` commands.
After reconnecting, an adapter sends a complete `snapshot` and starts a new
sequence space for that connection.

## Message envelope

Every message contains the following fields:

| Field | Type | Contract |
| --- | --- | --- |
| `protocol` | string | `kotonoha.adapter` |
| `version` | integer | `1` |
| `type` | string | `snapshot` or `clock` |
| `adapter` | string | Stable external adapter id; not a lyric provider id |
| `sequence` | integer | Non-negative sequence number for the connection |
| `capturedAt` | string | Non-empty producer timestamp, normally ISO 8601 |

Sequence ordering applies across both message types on one connection. A
message whose sequence is less than or equal to the last accepted sequence is
discarded.

## Snapshot

A snapshot is the complete state for a track and its lyric document. Send one
when the connection opens, when the track changes, and when the lyric document
changes. `lyrics` may be `null` while no lyrics are available.

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

### Playback object

`playback` is required. `playerId` and `status` are required. `positionS`,
`durationS`, and `track` may be `null`.

When `track` is present, `title`, `rawTitle`, `artist`, and `album` are strings.
`stableId`, `url`, and track duration are optional. Missing lyric metadata is
filled from the track when possible.

`status` is one of `Playing`, `Paused`, `Stopped`, or `Unknown`.

### Lyrics object

The `lyrics` object describes the final lyric artifact, not the player or
transport adapter that delivered it.

- `source` is a stable provider id, such as `lrclib`, `netease`, or `apple-music`.
- `sourceName` is an optional human-readable provider name.
- `timing` is `Line` or `Word` when `lines` is non-empty.
- `lines` are ordered; every line has non-negative `start` and `end` values.
- A word has either both non-negative `start` and `end` values or both values set to `null`.
- `title`, `artist`, `album`, and `durationS` are optional.

The document contains only source data. Display-derived fields such as
`currentLine`, `previousLine`, `nextLine`, `aroundLines`, and interlude state
are calculated by Kotonoha's display engine.

## Clock

A clock message updates playback position and status for the latest snapshot.
It is used for media-clock calibration; Kotonoha interpolates between accepted
observations and does not require one message per display frame. Send a clock
after a seek or playback-state change and at a stable lower frequency while
playback continues.

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

`trackRef` binds the clock to the latest accepted snapshot. When a snapshot
contains `stableId`, Kotonoha forms the reference as
`adapter:playerId:stableId`. A clock for another track is rejected and cannot
replace the current display. `positionS` may be `null` while unavailable.

## Adapter boundary

The adapter owns player-specific APIs, browser data, third-party payloads, and
their normalization. The boundary produces only the protocol shapes:

1. Read player state and track metadata.
2. Normalize player identity, track metadata, status, position, and duration into `playback`.
3. Fetch or parse lyrics into one complete `lyrics` document.
4. Set `lyrics.source` to the lyric provider id and use `lyrics.sourceName` only for its display label.
5. Publish `snapshot` for track or document changes and `clock` for position calibration.

Keep these identities separate:

| Identity | Example | Owner |
| --- | --- | --- |
| Transport adapter | `example-player` | External integration |
| Player instance | `example-window` | External player |
| Track identity | `track-123` | Player or catalog |
| Lyric provider | `lrclib` | Source that produced the document |

## Reconnection and invalid data

Reconnect with backoff and resend a complete snapshot after each connection.
Stop publishing when player data is no longer valid. Malformed or incomplete
lyric data is not converted into a valid snapshot; omit the document until a
complete, validated document is available.
