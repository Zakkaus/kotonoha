"""Feature-owned contracts for lyrics supplied by a live playback source."""

from __future__ import annotations

from dataclasses import dataclass

from ..playback.models import PlaybackObservation
from .match import MatchConfidence
from .models import LyricsDocument


@dataclass(frozen=True)
class LiveSourceMatch:
    """A live candidate that matches the currently selected player track."""

    client_id: int | str
    observation: PlaybackObservation
    document: LyricsDocument
    confidence: MatchConfidence


__all__ = ["LiveSourceMatch"]
