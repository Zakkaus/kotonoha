"""Stateful normalized playback clock owned by the application layer."""

from __future__ import annotations

from dataclasses import replace

from ..clock import MediaClock
from ..playback.identity import PlaybackTrackKey
from ..playback.models import PlaybackObservation, PlaybackStatus


class TimelineEngine:
    """Own playback calibration and smooth media-time estimation.

    Player adapters provide occasional observations. The engine re-anchors the
    shared :class:`MediaClock` on those observations and exposes a current
    observation for the display coordinator to project. It owns timing state;
    lyric selection and presentation rules live in ``DisplayEngine``.
    """

    def __init__(self, clock: MediaClock | None = None) -> None:
        self._clock = clock if clock is not None else MediaClock()
        self._observation: PlaybackObservation | None = None
        self._track_key: PlaybackTrackKey | None = None

    @property
    def observation(self) -> PlaybackObservation | None:
        """Return the latest normalized observation, if any."""
        return self._observation

    @property
    def playing(self) -> bool:
        """Return whether the interpolated clock currently advances."""
        return self._clock.playing

    def set_observation(self, observation: PlaybackObservation) -> PlaybackObservation:
        """Re-anchor the clock from a full player observation."""
        track_key = PlaybackTrackKey.from_observation(observation)
        if track_key != self._track_key:
            self._clock.reset()
            self._track_key = track_key
        self._observation = observation
        self._sync_clock(observation.position_s, observation.status)
        return observation

    def observe(
        self,
        position_s: float | None,
        status: PlaybackStatus | None,
    ) -> PlaybackObservation | None:
        """Apply a clock-only calibration and return its smooth observation."""
        observation = self._observation
        if observation is None:
            return None
        resolved_status = status if status is not None else observation.status
        self._sync_clock(position_s, resolved_status)
        self._observation = replace(
            observation,
            position_s=position_s if position_s is not None else observation.position_s,
            status=resolved_status,
        )
        # ``MediaClock`` may intentionally reject a slightly stale poll while
        # continuing to interpolate. Returning the raw value here would expose
        # that rejected sample to DisplayEngine and can move the current lyric
        # backwards across a line boundary for one frame.
        return self.current_observation()

    def advance(self) -> PlaybackObservation | None:
        """Return the latest observation with the clock's current position."""
        if self._observation is None:
            return None
        return self.current_observation()

    def current_observation(self) -> PlaybackObservation:
        """Return the current observation; callers must have supplied one first."""
        observation = self._observation
        if observation is None:
            raise RuntimeError("TimelineEngine has no observation")
        position = self._clock.now()
        if position is None:
            return observation
        return replace(observation, position_s=position)

    def reset(self) -> None:
        """Forget playback state and release the clock anchor."""
        self._clock.reset()
        self._observation = None
        self._track_key = None

    def _sync_clock(self, position_s: float | None, status: PlaybackStatus) -> None:
        if position_s is not None:
            self._clock.sync(position_s, status is PlaybackStatus.PLAYING)


__all__ = ["TimelineEngine"]
