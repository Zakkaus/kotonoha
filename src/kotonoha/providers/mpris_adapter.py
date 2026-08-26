"""Normalize MPRIS observations before application and display logic."""

from __future__ import annotations

from ..playback.models import PlaybackObservation, PlaybackStatus, TrackIdentity
from .mpris_track import TrackInfo


class MprisPlaybackAdapter:
    """Translate MPRIS-specific track facts into the shared playback contract."""

    def observe(
        self,
        info: TrackInfo,
        *,
        player_name: str,
        status: str,
        position_s: float | None,
        observed_at: float,
    ) -> PlaybackObservation:
        """Return one normalized playback observation without retaining D-Bus data."""
        playback_status = PlaybackStatus.from_wire(status)
        if playback_status is None:
            playback_status = PlaybackStatus.UNKNOWN
        track = TrackIdentity(
            adapter_id="mpris",
            player_id=player_name,
            stable_id=info.track_id if info.track_id else None,
            title=info.title,
            raw_title=info.reported_title if info.reported_title else info.title,
            artist=info.artist,
            album=info.album,
            url=info.url if info.url else None,
            duration_s=info.length_s,
        )
        return PlaybackObservation(
            adapter_id="mpris",
            player_id=player_name,
            track=track,
            status=playback_status,
            position_s=position_s,
            duration_s=info.length_s,
            observed_at=observed_at,
        )


__all__ = ["MprisPlaybackAdapter"]
