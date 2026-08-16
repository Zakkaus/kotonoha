"""Load lyrics from the LRC sidecar of a local audio file."""

from __future__ import annotations

from pathlib import Path

from ..model import LyricLine
from .lrc_parser import parse_lrc


def load_sidecar(audio_path: Path) -> list[LyricLine]:
    """Return parsed timed lines from the audio file's adjacent LRC sidecar."""
    if not audio_path.name:
        # A player publishing xesam:url = "file:///" reaches here as Path("/"), and
        # with_suffix raises ValueError on a path with no name — outside the OSError
        # this function otherwise handles. Nothing adjacent to a root can be a sidecar.
        return []
    sidecar = audio_path.with_suffix(".lrc")
    audio_directory = audio_path.parent.resolve()

    try:
        if sidecar.resolve().parent != audio_directory:
            return []
        raw = sidecar.read_bytes()
    except OSError:
        return []

    for encoding in ("utf-8", "gb18030"):
        try:
            return parse_lrc(raw.decode(encoding))
        except UnicodeDecodeError:
            continue
    return []
