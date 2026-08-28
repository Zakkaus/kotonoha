# Cider HTTP adapter

- `case_id`: `adapter.cider-http`
- `status`: `Implemented`
- `owner`: Cider player adapter and lyrics ingress
- `old_behavior`: Cider lyrics depended on a separately installed probe that pushed WebSocket frames. The frame mixed player facts, lyric timing, and display-derived current/previous/next line state.
- `new_contract`: `CiderApiClient` reads Cider's public HTTP API. A non-empty optional token is sent as `apptoken`; an empty token is omitted. The playback adapter reads one complete playback observation about once per second. When the track changes, the lyrics adapter fetches one complete timed document from Cider and normalizes the final `source.provider` into a stable `source_id` while retaining its raw display name as `source_name`. `MediaClock` advances the display between calibration samples.
- `user_impact`: The Cider plugin is no longer required for the current path. Users with API authentication disabled can connect without a token; users with authentication enabled can set the token in Settings -> Sources, where it is stored in `config.json` with the other settings. Lyrics timing remains smooth without polling Cider for every display frame.
- `reason`: Cider's documented API already exposes the complete lyric timing and current playback position. Pulling that public contract avoids coupling the primary path to an internal plugin transport and keeps the final lyric provider distinct from Cider as the transport/player adapter.
- `replacement_tests`: `tests/test_cider_api.py`, `tests/test_lyrics_protocol.py`, `tests/test_lyrics_workflow.py`, and the live no-token Cider HTTP adapter check.
- `removal_condition`: Completed. The Cider-specific receiver route and legacy decoder were removed when the generic `kotonoha.adapter` v1 receiver became the external-player boundary.
