"""Narrow contracts and values shared by live source adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias

from ..lyrics.match import MatchConfidence, TrackMetadata
from ..lyrics.models import LyricsDocument
from ..playback.models import PlaybackObservation

SourceClientId: TypeAlias = int | str
SourceMode: TypeAlias = Literal["standalone", "external", "live"]


@dataclass(frozen=True)
class LiveSourceCandidate:
    """The latest normalized facts retained for one live source client."""

    client_id: SourceClientId
    observation: PlaybackObservation
    document: LyricsDocument | None
    confidence: MatchConfidence = MatchConfidence.HIGH


@dataclass(frozen=True)
class LiveSourceMatch:
    """A live candidate that matches the currently selected player track."""

    client_id: SourceClientId
    observation: PlaybackObservation
    document: LyricsDocument
    confidence: MatchConfidence


@dataclass(frozen=True)
class LiveSourceTiming:
    """A clock update tied to the candidate snapshot it followed."""

    client_id: SourceClientId
    track_ref: str | None
    current_time: float | None
    is_playing: bool | None
    duration_s: float | None = None


class SourceIngressPort(Protocol):
    """Candidate and clock operations needed by generic adapter ingress."""

    def observe(
        self,
        client_id: SourceClientId,
        observation: PlaybackObservation,
        document: LyricsDocument | None,
    ) -> None: ...

    def observe_clock(
        self,
        client_id: SourceClientId,
        track_ref: str | None,
        current_time: float | None,
        is_playing: bool | None,
    ) -> bool: ...

    def accepts(self, client_id: SourceClientId) -> bool: ...

    def drop_client(self, client_id: SourceClientId) -> None: ...


class SourcePublicationPort(SourceIngressPort, Protocol):
    """Additional ownership operations needed by a polling source."""

    @property
    def mode(self) -> SourceMode: ...

    def clear_client(self, client_id: SourceClientId) -> None: ...


class SourceResolutionPort(Protocol):
    """Late-source selection operations needed by lyric resolution."""

    @property
    def live_active(self) -> bool: ...

    @property
    def revision(self) -> int: ...

    def current_match(self, track: TrackMetadata) -> LiveSourceMatch | None: ...

    def select_external(self) -> bool: ...

    def select_live(self, client_id: SourceClientId) -> bool: ...

    def select_standalone(self) -> None: ...


class SourceClockPort(Protocol):
    """Source facts needed while an external player advances its clock."""

    def accepts(self, client_id: SourceClientId) -> bool: ...

    def current_timing(self, track: TrackMetadata) -> LiveSourceTiming | None: ...


class MprisSourcePort(SourceResolutionPort, SourceClockPort, Protocol):
    """Combined live-source capabilities used by the MPRIS workflow only."""


__all__ = [
    "LiveSourceCandidate",
    "LiveSourceMatch",
    "LiveSourceTiming",
    "SourceClientId",
    "SourceClockPort",
    "SourceIngressPort",
    "MprisSourcePort",
    "SourceMode",
    "SourcePublicationPort",
    "SourceResolutionPort",
]
