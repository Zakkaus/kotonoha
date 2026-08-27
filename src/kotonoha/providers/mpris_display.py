"""Display and timing binding for the MPRIS provider."""

from __future__ import annotations

import time

from ..display.coordinator import DisplayCoordinator
from ..display.models import EMPTY_FRAME, ResolutionState
from ..lyrics.models import LyricLine, LyricsDocument
from ..lyrics.ownership import SourceOwnershipCoordinator
from ..playback.models import PlaybackObservation, PlaybackStatus
from .mpris_adapter import MprisPlaybackAdapter
from .mpris_playback import PlaybackSample
from .mpris_timeline import MprisPositionCalibrator
from .mpris_track import TrackCommit, TrackInfo


class MprisDisplayBinding:
    """Translate MPRIS samples into calibrated display updates."""

    def __init__(
        self,
        display: DisplayCoordinator,
        *,
        ownership: SourceOwnershipCoordinator,
        playback_adapter: MprisPlaybackAdapter,
    ) -> None:
        """Create a binding around the application display port."""
        self._display = display
        self._ownership = ownership
        self._playback_adapter = playback_adapter
        self._timeline = MprisPositionCalibrator()
        self._last_observation: PlaybackObservation | None = None

    @property
    def last_observation(self) -> PlaybackObservation | None:
        """Return the latest normalized sample used for display updates."""
        return self._last_observation

    def observe_sample(self, sample: PlaybackSample, commit: TrackCommit | None) -> None:
        """Record a sample and calibrate the active external timeline."""
        observation = sample.observation
        self._last_observation = observation
        if observation.position_s is not None and not sample.transitioning and commit is not None:
            self._timeline.calibrate(commit, observation.position_s, observation.observed_at)

    def publish_external_sample(self, commit: TrackCommit, sample: PlaybackSample) -> None:
        """Publish the calibrated external timeline, honoring a live clock when present."""
        observation = sample.observation
        position = observation.position_s
        if position is not None:
            position = max(0.0, position - self._timeline.offset)
        status = observation.status
        live_timing = self._ownership.current_timing(commit.info.metadata())
        if live_timing is not None and live_timing.current_time is not None:
            position = live_timing.current_time
            if live_timing.is_playing is not None:
                status = PlaybackStatus.PLAYING if live_timing.is_playing else PlaybackStatus.PAUSED
        if position is not None:
            self._display.tick(position, status)

    def observe_commit(self, commit: TrackCommit) -> None:
        """Start a fresh calibration epoch for a stable track commit."""
        self._timeline.observe_commit(commit)

    def reconcile(
        self,
        commit: TrackCommit,
        lines: tuple[LyricLine, ...],
        duration_s: float | None,
        position_s: float | None,
    ) -> None:
        """Align an external lyric document with the current MPRIS position."""
        self._timeline.reconcile(commit, lines, duration_s, position_s)

    def publish_resolution(
        self,
        observation: PlaybackObservation,
        resolution: ResolutionState,
    ) -> None:
        """Publish an explicit resolution state without lyric content."""
        self._display.publish_resolution(observation, None, resolution)

    def publish_document(
        self,
        document: LyricsDocument,
        info: TrackInfo,
        *,
        commit: TrackCommit | None,
        position_s: float | None = None,
        playing: bool | None = None,
        player_name: str | None = None,
        observed_at: float | None = None,
    ) -> None:
        """Publish a source-owned document against current or supplied playback facts."""
        latest = self._last_observation
        if (
            latest is not None
            and latest.track is not None
            and latest.track.title == info.title
            and position_s is None
            and playing is None
            and player_name is None
            and observed_at is None
        ):
            observation = latest
        else:
            resolved_player_name = (
                player_name
                if player_name is not None
                else commit.player_name
                if commit is not None
                else latest.player_id
                if latest is not None
                else ""
            )
            resolved_position = (
                position_s
                if position_s is not None
                else latest.position_s
                if latest is not None and latest.position_s is not None
                else 0.0
            )
            resolved_playing = (
                playing
                if playing is not None
                else latest is None or latest.status is PlaybackStatus.PLAYING
            )
            observation = self._playback_adapter.observe(
                info,
                player_name=resolved_player_name,
                status="Playing" if resolved_playing else "Paused",
                position_s=max(0.0, resolved_position),
                observed_at=time.monotonic() if observed_at is None else observed_at,
            )
        self._display.publish(observation, document)

    def reset(self) -> None:
        """Clear display-side calibration and the latest observation."""
        self._timeline.reset()
        self._last_observation = None
        self._display.publish_frame(EMPTY_FRAME)


__all__ = ["MprisDisplayBinding"]
