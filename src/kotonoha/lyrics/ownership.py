"""Compatibility exports for the application-owned source gate."""

# TODO: remove this module after lyric adapter callers migrate to app.source_gate.
from ..app.source_gate import (
    LiveSourceCandidate,
    LiveSourceMatch,
    LiveSourceTiming,
    SourceClientId,
    SourceOwnershipCoordinator,
)

__all__ = [
    "LiveSourceCandidate",
    "LiveSourceMatch",
    "LiveSourceTiming",
    "SourceClientId",
    "SourceOwnershipCoordinator",
]
