"""Pure timeline rules used by the object-oriented presentation adapter."""

from __future__ import annotations

from dataclasses import replace
from statistics import median

from ..clock import MediaClock
from ..lyrics.models import LyricLine
from ..playback.models import PlaybackObservation, PlaybackStatus
from .models import Interlude

# How far past the song's own pace a span must run before the music after a line
# counts as an interlude rather than a long-held phrase.
_INTERLUDE_FACTOR = 2.5
_INTERLUDE_FLOOR_S = 12.0
_SWEEP_CAP_FACTOR = 2.0


class TimelineEngine:
    """Own playback calibration and smooth media-time estimation.

    Player adapters provide occasional observations.  The engine re-anchors the
    shared :class:`MediaClock` on those observations and exposes a current
    observation for the display coordinator to project.  It owns timing state;
    it does not know about lyrics, Qt, or any concrete player adapter.
    """

    def __init__(self, clock: MediaClock | None = None) -> None:
        self._clock = clock if clock is not None else MediaClock()
        self._observation: PlaybackObservation | None = None
        self._track_key: tuple[object, ...] | None = None

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
        track_key = _track_key(observation)
        if track_key != self._track_key:
            self._clock.reset()
            self._track_key = track_key
        self._observation = observation
        self._sync_clock(observation.position_s, observation.status)
        return observation

    def observe(
        self,
        position_s: float | None,
        is_playing: bool | None,
    ) -> PlaybackObservation | None:
        """Apply a clock-only calibration and return the current observation."""
        observation = self._observation
        if observation is None:
            return None
        playing = is_playing if isinstance(is_playing, bool) else True
        self._sync_clock(position_s, PlaybackStatus.PLAYING if playing else PlaybackStatus.PAUSED)
        self._observation = replace(
            observation,
            position_s=position_s if position_s is not None else observation.position_s,
            status=PlaybackStatus.PLAYING if playing else PlaybackStatus.PAUSED,
        )
        return self._observation

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


def _track_key(observation: PlaybackObservation) -> tuple[object, ...]:
    """Return the identity that must invalidate a previous clock anchor."""
    track = observation.track
    if track is None:
        return (observation.adapter_id, observation.player_id, None)
    return (
        observation.adapter_id,
        observation.player_id,
        track.stable_id,
        track.title,
        track.artist,
        track.album,
    )


def find_current_index(lines: list[LyricLine], position: float) -> int:
    """Return the last line whose start is not after ``position``."""
    index = -1
    for index_candidate, line in enumerate(lines):
        if line.start <= position:
            index = index_candidate
        else:
            break
    return index


def typical_span(lines: list[LyricLine]) -> float:
    """Return the median positive distance between neighboring line starts."""
    spans = [lines[index + 1].start - lines[index].start for index in range(len(lines) - 1)]
    usable = [span for span in spans if span > 0.0]
    return median(usable) if usable else 0.0


def in_interlude(
    lines: list[LyricLine], index: int, position: float, duration_s: float | None = None
) -> bool:
    """Return whether ``position`` is in an instrumental gap after ``index``."""
    if not 0 <= index < len(lines):
        return False
    line = lines[index]
    if index + 1 == len(lines):
        return duration_s is not None and duration_s > line.end and position > line.end
    span = lines[index + 1].start - line.start
    typical = typical_span(lines)
    if typical <= 0.0 or span <= _INTERLUDE_FACTOR * typical or span < _INTERLUDE_FLOOR_S:
        return False
    return position > line.start + typical


def interlude_at(
    lines: list[LyricLine], index: int, position: float, duration_s: float | None = None
) -> Interlude | None:
    """Return the active instrumental gap, including an intro or outro gap."""
    if not lines:
        return None
    if index < 0:
        return Interlude(0.0, lines[0].start) if position < lines[0].start else None
    if not in_interlude(lines, index, position, duration_s):
        return None
    line = lines[index]
    if index + 1 == len(lines):
        if duration_s is None or duration_s <= line.end:
            return None
        return Interlude(line.end, duration_s)
    return Interlude(line.start + typical_span(lines), lines[index + 1].start)


def swept_line(line: LyricLine, typical: float) -> LyricLine:
    """Limit only the highlight sweep; keep the lyric line visible."""
    if line.has_word_timing:
        sung = max((word.end for word in line.words if word.end is not None), default=None)
        return line if sung is None or sung >= line.end else replace(line, end=sung)
    if typical <= 0.0:
        return line
    capped = line.start + _SWEEP_CAP_FACTOR * typical
    return line if capped >= line.end else replace(line, end=capped)


def song_timing(lines: list[LyricLine]) -> str:
    """Return the legacy timing label for a line collection."""
    return "Word" if any(line.has_word_timing for line in lines) else "Line"
