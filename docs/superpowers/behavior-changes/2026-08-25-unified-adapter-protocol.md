# Unified lyrics adapter protocol

- `case_id`: `adapter.protocol.v1.display-projection`
- `status`: `Implemented`
- `owner`: lyrics/display adapter boundary
- `old_behavior`: The Cider WebSocket payload mixed raw playback facts with `currentLine`, `previousLine`, `nextLine`, and `aroundLines`; the MPRIS path built a separate `LyricsSnapshot` directly from provider lines.
- `new_contract`: Versioned `kotonoha.adapter` messages distinguish `snapshot` and `clock`. A snapshot carries a normalized playback observation and a complete timed lyric document. Current-line selection, interlude detection, and surrounding context are produced only by `DisplayEngine`; Qt receives the result through `QtDisplayPublisher`.
- `user_impact`: Adapter payloads no longer duplicate display decisions, so future players can provide the same timed document contract and receive identical lyric selection behavior. Pre-v1 Cider frames are rejected at the versioned boundary.
- `reason`: Display-derived fields cannot be kept consistent when each player adapter computes them independently, and they prevent a future player from reusing the Kotonoha presentation rules.
- `replacement_tests`: `tests/test_lyrics_protocol.py`, `tests/test_lyrics_adapters.py`, `tests/test_select.py`, `tests/test_receiver.py`, and `tests/test_mpris_provider.py`.
- `removal_condition`: Completed. `LegacyCiderPayloadDecoder`, legacy Cider fields, and legacy `LyricsSnapshot` publishing are removed; only `DisplayFrame` is published to Qt.
