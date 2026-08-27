"""Text transformations applied at the display boundary."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from ..lyrics.hanzi_fold import convert_script
from ..lyrics.models import LyricsDocument
from .models import DisplayScript


class DisplayTextTransformer(Protocol):
    """Transform canonical lyric text without changing its timing."""

    def document(self, value: LyricsDocument, script: DisplayScript) -> LyricsDocument: ...

    def text(self, value: str, script: DisplayScript) -> str: ...


class ScriptTextTransformer:
    """Apply the configured Chinese-script conversion to rendered text."""

    def document(self, value: LyricsDocument, script: DisplayScript) -> LyricsDocument:
        """Return a copied document with transformed lines and word text."""
        if script is DisplayScript.OFF:
            return value
        lines = tuple(
            replace(
                line,
                text=self.text(line.text, script),
                translation=self.text(line.translation, script),
                words=tuple(replace(word, text=self.text(word.text, script)) for word in line.words),
            )
            for line in value.lines
        )
        return replace(value, lines=lines)

    def text(self, value: str, script: DisplayScript) -> str:
        """Convert one display string while leaving the source document untouched."""
        return convert_script(value, script.value)


__all__ = ["DisplayTextTransformer", "ScriptTextTransformer"]
