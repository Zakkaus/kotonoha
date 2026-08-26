"""Object-owned projection from canonical lyrics and playback to a display frame."""

from __future__ import annotations

from ..lyrics.models import LyricsDocument
from ..playback.models import PlaybackObservation, PlaybackStatus, TrackIdentity
from .models import DisplayFrame, DisplayState
from .timeline import find_current_index, in_interlude, interlude_at, swept_line, typical_span


class LyricsPresentationAdapter:
    """Build the one renderer-facing frame shared by every input adapter."""

    def project_observation(
        self,
        playback: PlaybackObservation,
        document: LyricsDocument | None,
        *,
        state: DisplayState | None = None,
    ) -> DisplayFrame:
        """Project one normalized playback/document pair into a display frame."""
        resolved_state = state
        if resolved_state is None:
            if playback.track is None and document is None:
                resolved_state = DisplayState.NO_TRACK
            elif document is not None and document.lines:
                resolved_state = DisplayState.LYRICS_AVAILABLE
            else:
                resolved_state = DisplayState.LYRICS_NOT_FOUND
        return self.project(
            document,
            playback.position_s,
            track=playback.track,
            is_playing=playback.status is PlaybackStatus.PLAYING,
            state=resolved_state,
        )

    def project(
        self,
        document: LyricsDocument | None,
        position_s: float | None,
        *,
        track: TrackIdentity | None,
        is_playing: bool,
        state: DisplayState | None = None,
    ) -> DisplayFrame:
        """Project a document and playback clock without touching Qt state."""
        lines = list(document.lines) if document is not None else []
        resolved_state = state
        if resolved_state is None:
            resolved_state = DisplayState.LYRICS_AVAILABLE if lines else DisplayState.LYRICS_NOT_FOUND
        if not lines or resolved_state is not DisplayState.LYRICS_AVAILABLE or position_s is None:
            return DisplayFrame(
                state=resolved_state,
                track=track,
                document=document,
                current_time=position_s,
                is_playing=is_playing,
            )

        index = find_current_index(lines, position_s)
        duration_s = document.duration_s if document is not None else None
        quiet = in_interlude(lines, index, position_s, duration_s)
        current = None if quiet else (lines[index] if 0 <= index < len(lines) else None)
        if current is not None:
            current = swept_line(current, typical_span(lines))
        previous = lines[index] if quiet else (lines[index - 1] if index - 1 >= 0 else None)
        interlude = interlude_at(lines, index, position_s, duration_s)
        next_line = lines[index + 1] if 0 <= index + 1 < len(lines) else None
        around = tuple(lines[max(0, index - 2) : index + 3])
        return DisplayFrame(
            state=resolved_state,
            track=track,
            document=document,
            current_time=position_s,
            is_playing=is_playing,
            previous=previous,
            current=current,
            next=next_line,
            around=around,
            interlude=interlude,
        )
