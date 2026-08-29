"""Adapters for Cider's structured lyrics API responses."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..playback.models import TrackIdentity
from .models import LyricLine, LyricsDocument, LyricsOrigin, LyricWord, TimingKind, validate_document


class CiderLyricsPayloadError(ValueError):
    """A Cider lyrics response failed its typed boundary contract."""


@dataclass(frozen=True)
class CiderLyricsProvider:
    """The final lyrics provider reported by Cider, independent of transport."""

    identifier: str
    name: str


class CiderLyricsResponseAdapter:
    """Normalize one Cider lyrics envelope into a canonical lyric document."""

    def adapt(
        self,
        payload: Mapping[str, object],
        *,
        track: TrackIdentity,
        duration_s: float | None,
    ) -> LyricsDocument:
        """Parse provider identity, timing, and lines from one API response."""
        provider = self._provider(payload.get("source"))
        song_id = self._optional_text(payload.get("id"), "lyrics.id")
        timing = self._timing(provider_payload=payload.get("source"))
        raw_lines = self._list(payload.get("lines"), "lyrics.lines")
        if raw_lines and timing is None:
            raise CiderLyricsPayloadError("lyrics with lines must declare a timing type")
        lines = tuple(self._line(value, index) for index, value in enumerate(raw_lines))
        document = LyricsDocument(
            source_id=provider.identifier,
            source_name=provider.name,
            song_id=song_id,
            timing=timing,
            language=self._optional_text_from_source(payload.get("source"), "language"),
            title=track.title,
            artist=track.artist,
            album=track.album,
            duration_s=duration_s if duration_s is not None else track.duration_s,
            lines=lines,
            origin=LyricsOrigin.LIVE,
        )
        try:
            validate_document(document)
        except ValueError as exc:
            raise CiderLyricsPayloadError(str(exc)) from exc
        return document

    def translations(self, payload: Mapping[str, object]) -> tuple[str, ...]:
        """Extract ordered line translations from Cider's translation response."""
        raw_translations = self._list(payload.get("translations"), "translations")
        result: list[str] = []
        for index, value in enumerate(raw_translations):
            item = self._mapping(value, f"translations[{index}]")
            result.append(self._text(item.get("translation"), f"translations[{index}].translation"))
        return tuple(result)

    @staticmethod
    def provider_identifier(provider_name: str) -> str:
        """Return a stable source id while preserving the API's display name."""
        aliases = {
            "apple music": "apple-music",
            "apple-music": "apple-music",
            "musixmatch": "musixmatch",
            "netease": "netease",
            "netease cloud music": "netease",
            "user": "user",
        }
        normalized = provider_name.strip().casefold()
        known = aliases.get(normalized)
        if known is not None:
            return known
        slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
        if normalized.isascii() and slug:
            return slug
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
        return f"provider-{digest}"

    @classmethod
    def _provider(cls, value: object) -> CiderLyricsProvider:
        source = cls._mapping(value, "lyrics.source")
        name = cls._non_empty_text(source.get("provider"), "lyrics.source.provider")
        return CiderLyricsProvider(cls.provider_identifier(name), name)

    @classmethod
    def _timing(cls, *, provider_payload: object) -> TimingKind | None:
        source = cls._mapping(provider_payload, "lyrics.source")
        raw_timing = cls._optional_text(source.get("timingType"), "lyrics.source.timingType")
        if raw_timing is None or raw_timing == "None":
            return None
        try:
            return TimingKind(raw_timing)
        except ValueError as exc:
            raise CiderLyricsPayloadError(f"unsupported Cider lyric timing {raw_timing!r}") from exc

    @classmethod
    def _line(cls, value: object, index: int) -> LyricLine:
        raw = cls._mapping(value, f"lyrics.lines[{index}]")
        start = cls._number(raw.get("start"), f"lyrics.lines[{index}].start", minimum=0.0)
        end = cls._number(raw.get("end"), f"lyrics.lines[{index}].end", minimum=start)
        line_id = cls._optional_text(raw.get("id"), f"lyrics.lines[{index}].id") or str(index)
        text = cls._text(raw.get("text"), f"lyrics.lines[{index}].text")
        raw_words = cls._list(raw.get("words", []), f"lyrics.lines[{index}].words")
        words = tuple(cls._word(word, index, word_index) for word_index, word in enumerate(raw_words))
        return LyricLine(index, line_id, start, end, text, "", words)

    @classmethod
    def _word(cls, value: object, line_index: int, word_index: int) -> LyricWord:
        raw = cls._mapping(value, f"lyrics.lines[{line_index}].words[{word_index}]")
        start = cls._number(raw.get("start"), "lyric word start", minimum=0.0)
        end = cls._number(raw.get("end"), "lyric word end", minimum=start)
        text = cls._text(raw.get("text"), "lyric word text")
        return LyricWord(start, end, text)

    @classmethod
    def _optional_text_from_source(cls, value: object, field: str) -> str | None:
        source = cls._mapping(value, "lyrics.source")
        return cls._optional_text(source.get(field), f"lyrics.source.{field}")

    @staticmethod
    def _mapping(value: object, field: str) -> Mapping[str, object]:
        if not isinstance(value, Mapping):
            raise CiderLyricsPayloadError(f"{field} must be an object")
        return value

    @staticmethod
    def _list(value: object, field: str) -> Sequence[object]:
        if not isinstance(value, list):
            raise CiderLyricsPayloadError(f"{field} must be an array")
        return value

    @staticmethod
    def _text(value: object, field: str) -> str:
        if not isinstance(value, str):
            raise CiderLyricsPayloadError(f"{field} must be a string")
        return value

    @staticmethod
    def _non_empty_text(value: object, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise CiderLyricsPayloadError(f"{field} must be a non-empty string")
        return value

    @classmethod
    def _optional_text(cls, value: object, field: str) -> str | None:
        if value is None:
            return None
        return cls._text(value, field)

    @staticmethod
    def _number(value: object, field: str, *, minimum: float | None = None) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CiderLyricsPayloadError(f"{field} must be a number")
        parsed = float(value)
        if not math.isfinite(parsed) or (minimum is not None and parsed < minimum):
            raise CiderLyricsPayloadError(f"{field} is outside its valid range")
        return parsed


__all__ = [
    "CiderLyricsPayloadError",
    "CiderLyricsProvider",
    "CiderLyricsResponseAdapter",
]
