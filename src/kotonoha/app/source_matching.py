"""Pure matching rules for normalized live source candidates."""

from __future__ import annotations

from ..lyrics.match import Candidate, MatchConfidence, TrackMetadata, evaluate_match
from .source_contracts import LiveSourceCandidate


def has_lyrics(candidate: LiveSourceCandidate) -> bool:
    """Return whether a candidate carries at least one displayable lyric line."""
    return candidate.document is not None and bool(candidate.document.lines)


def candidate_metadata(candidate: LiveSourceCandidate) -> TrackMetadata | None:
    """Extract matching metadata from playback facts or the lyric document."""
    track = candidate.observation.track
    document = candidate.document
    if track is not None:
        return TrackMetadata(track.title, track.artist, track.album, track.duration_s)
    if document is not None and document.title is not None:
        return TrackMetadata(
            document.title,
            document.artist or "",
            document.album or "",
            document.duration_s,
        )
    return None


def accepted_confidence(
    candidate: LiveSourceCandidate,
    track: TrackMetadata,
    *,
    require_lyrics: bool,
) -> MatchConfidence | None:
    """Return the confidence accepted for a candidate, or ``None``."""
    if require_lyrics and not has_lyrics(candidate):
        return None
    metadata = candidate_metadata(candidate)
    if metadata is None or not metadata.title:
        return None
    document = candidate.document
    evidence = evaluate_match(
        Candidate(
            song_id=document.song_id if document is not None and document.song_id else "live",
            title=metadata.title,
            artist=metadata.artist,
            album=metadata.album,
            duration_s=metadata.duration_s,
        ),
        track,
    )
    if evidence.confidence is MatchConfidence.HIGH:
        return MatchConfidence.HIGH
    if evidence.confidence is MatchConfidence.MEDIUM and evidence.title_exact:
        return MatchConfidence.MEDIUM
    return None


__all__ = ["accepted_confidence", "candidate_metadata", "has_lyrics"]
