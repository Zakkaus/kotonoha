"""Extract provider-owned lyric identifiers from MPRIS metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class LyricsHint:
    provider: str
    song_id: str | None = None
    local_path: Path | None = None


def from_player(identity: str, bus_name: str, track_id: str, url: str) -> LyricsHint | None:
    """Return an exact provider id, or a local path, for known players only."""
    if identity in {"ElectronNCM", "Qcm"} or "musicfox" in bus_name or "NeteaseCloudMusicGtk4" in bus_name:
        song_id = track_id.rsplit("/", 1)[-1]
        return LyricsHint("netease", song_id) if song_id else None
    if identity == "feeluown":
        for prefix, provider in (("fuo://netease/songs/", "netease"), ("fuo://qqmusic/songs/", "qqmusic")):
            if url.startswith(prefix):
                song_id = url.removeprefix(prefix)
                return LyricsHint(provider, song_id) if song_id else None
    if identity == "YesPlayMusic" and url.startswith("/trackid/"):
        song_id = url.removeprefix("/trackid/")
        return LyricsHint("netease", song_id) if song_id else None
    if url.startswith("file://"):
        parsed = urlparse(url)
        if parsed.path:
            return LyricsHint("local", local_path=Path(unquote(parsed.path)))
    return None
