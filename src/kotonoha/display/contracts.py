"""Narrow display publication ports for external adapters."""

from __future__ import annotations

from typing import Protocol

from ..lyrics.models import LyricsDocument
from ..playback.models import PlaybackObservation, PlaybackStatus
from .models import DisplayFrame, ResolutionState


class AdapterDisplayPort(Protocol):
    """Display operations needed by the canonical adapter receiver."""

    def publish(self, playback: PlaybackObservation, document: LyricsDocument | None) -> DisplayFrame: ...

    def tick(self, position_s: float | None, status: PlaybackStatus) -> None: ...


class CiderDisplayPort(Protocol):
    """Display operations needed by Cider's resolved playback snapshots."""

    def publish(self, playback: PlaybackObservation, document: LyricsDocument | None) -> DisplayFrame: ...

    def publish_resolution(
        self,
        playback: PlaybackObservation,
        document: LyricsDocument | None,
        resolution: ResolutionState,
    ) -> DisplayFrame: ...


class MprisDisplayPort(Protocol):
    """Display operations needed by MPRIS timing and lyric binding."""

    def publish(self, playback: PlaybackObservation, document: LyricsDocument | None) -> DisplayFrame: ...

    def publish_resolution(
        self,
        playback: PlaybackObservation,
        document: LyricsDocument | None,
        resolution: ResolutionState,
    ) -> DisplayFrame: ...

    def publish_frame(self, frame: DisplayFrame) -> bool: ...

    def tick(self, position_s: float | None, status: PlaybackStatus) -> None: ...


__all__ = ["AdapterDisplayPort", "CiderDisplayPort", "MprisDisplayPort"]
