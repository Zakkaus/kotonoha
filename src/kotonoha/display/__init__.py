"""Pure display contracts and timeline projection."""

from .layout import FontFitPolicy, TextFitDecision
from .models import (
    EMPTY_FRAME,
    DisplayDiagnostic,
    DisplayFrame,
    DisplayInput,
    DisplayOptions,
    DisplayScript,
    DisplayState,
    Interlude,
    InterludeCountdown,
    InterludeMarkerStyle,
    LineProgress,
    LyricsDisplayStatus,
    ResolutionState,
    WordProgress,
)

__all__ = [
    "EMPTY_FRAME",
    "DisplayDiagnostic",
    "DisplayFrame",
    "DisplayInput",
    "DisplayOptions",
    "DisplayScript",
    "DisplayState",
    "FontFitPolicy",
    "Interlude",
    "InterludeCountdown",
    "InterludeMarkerStyle",
    "LineProgress",
    "LyricsDisplayStatus",
    "ResolutionState",
    "TextFitDecision",
    "WordProgress",
]
