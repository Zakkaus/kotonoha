"""Canonical identity rules shared by playback, display, and configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .models import PlaybackObservation

TRACK_IDENTITY_SEPARATOR: Final[str] = "\x1f"


@dataclass(frozen=True, slots=True)
class TrackMetadataKey:
    """Metadata identity used to compare two observations of one recording."""

    stable_id: str | None
    title: str
    artist: str
    album: str


@dataclass(frozen=True, slots=True)
class PlaybackTrackKey:
    """Full adapter/player identity used to invalidate a playback clock."""

    adapter_id: str
    player_id: str
    stable_id: str | None
    title: str
    artist: str
    album: str

    @classmethod
    def from_observation(cls, observation: PlaybackObservation) -> PlaybackTrackKey:
        """Build a clock identity from one normalized playback observation."""
        track = observation.track
        if track is None:
            return cls(observation.adapter_id, observation.player_id, None, "", "", "")
        return cls(
            observation.adapter_id,
            observation.player_id,
            track.stable_id,
            track.title,
            track.artist,
            track.album,
        )

    @classmethod
    def from_mpris(
        cls,
        player_name: str,
        metadata: TrackMetadataKey,
    ) -> PlaybackTrackKey:
        """Build a playback identity for normalized MPRIS metadata."""
        return cls(
            "mpris",
            player_name,
            metadata.stable_id,
            metadata.title,
            metadata.artist,
            metadata.album,
        )


def track_identity_key(title: str, artist: str, duration_s: float | None = None) -> str:
    """Return the stable offset key for one recording's normalized title and artist."""
    del duration_s  # Duration varies by source and must not split one recording's key.
    return TRACK_IDENTITY_SEPARATOR.join((title.strip().casefold(), artist.strip().casefold()))


__all__ = [
    "TRACK_IDENTITY_SEPARATOR",
    "PlaybackTrackKey",
    "TrackMetadataKey",
    "track_identity_key",
]
