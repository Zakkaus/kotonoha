"""Read-only current lyric source status used by lyric selection surfaces."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QWidget

from ...display.models import LyricsDisplayStatus
from ...lyrics.models import LyricsCacheState, LyricsOrigin
from ...strings import Translator


class LyricsStatusBand(QFrame):
    """Render the active lyric provider, acquisition path, player, and cache state."""

    def __init__(
        self,
        status: LyricsDisplayStatus,
        translator: Translator,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._translator = translator
        self._source_value = QLabel()
        self._origin_value = QLabel()
        self._playback_value = QLabel()
        self._cache_value = QLabel()
        self.setObjectName("lyricsStatus")
        self._build_layout()
        self.set_status(status)

    def set_status(self, status: LyricsDisplayStatus) -> None:
        """Replace the visible status after a lyric selection takes effect."""
        source = _format_lyrics_source(status, self._translator)
        self._source_value.setText(source)
        self._source_value.setToolTip(source)
        self._origin_value.setText(_format_origin(status.origin, self._translator))
        self._playback_value.setText(_format_playback_source(status.playback_source, self._translator))
        self._cache_value.setText(_format_cache_state(status.cache_state, self._translator))

    def _build_layout(self) -> None:
        """Build the compact four-column status layout once."""
        grid = QGridLayout(self)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        heading = QLabel(self._translator.text("search.current_lyrics"))
        heading.setObjectName("sectionTitle")
        grid.addWidget(heading, 0, 0, 1, 4)
        values = (
            ("search.status.source", self._source_value),
            ("search.status.origin", self._origin_value),
            ("search.status.player", self._playback_value),
            ("search.status.cache", self._cache_value),
        )
        for column, (key, content) in enumerate(values):
            label = QLabel(self._translator.text(key))
            label.setObjectName("metaLabel")
            content.setObjectName("metaValue")
            content.setWordWrap(True)
            content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(label, 1, column)
            grid.addWidget(content, 2, column)
            grid.setColumnStretch(column, 1)


def _format_lyrics_source(status: LyricsDisplayStatus, translator: Translator) -> str:
    """Format a source name while localizing known stable source identifiers."""
    source_id = status.lyrics_source_id
    source_name = status.lyrics_source_name
    if not source_name and not source_id:
        return translator.text("search.current_lyrics.none")
    if source_name and source_id and source_name != source_id:
        return f"{source_name} ({_localize_source_id(source_id, translator)})"
    if source_id:
        return _localize_source_id(source_id, translator)
    return source_name or translator.text("search.current_lyrics.none")


def _localize_source_id(source_id: str, translator: Translator) -> str:
    """Use the existing provider label when an identifier has a translation."""
    key = f"src.{source_id}"
    localized = translator.text(key)
    return source_id if localized == key else localized


def _format_origin(value: LyricsOrigin | None, translator: Translator) -> str:
    """Format the explicit document acquisition origin for the status band."""
    keys = {
        LyricsOrigin.NETWORK: "search.origin.network",
        LyricsOrigin.CACHE: "search.origin.cache",
        LyricsOrigin.LIVE: "search.origin.live",
        LyricsOrigin.SIDECAR: "search.origin.sidecar",
        LyricsOrigin.EMBEDDED: "search.origin.embedded",
        LyricsOrigin.ADAPTER: "search.origin.adapter",
        LyricsOrigin.MANUAL: "search.origin.manual",
    }
    if value is None:
        return translator.text("search.current_lyrics.none")
    return translator.text(keys[value])


def _format_playback_source(value: str | None, translator: Translator) -> str:
    """Format the playback adapter without hiding an unknown adapter identifier."""
    if value is None or not value:
        return translator.text("search.current_lyrics.none")
    keys = {
        "mpris": "search.playback.mpris",
        "cider": "search.playback.cider",
        "adapter": "search.playback.adapter",
    }
    key = keys.get(value)
    return translator.text(key) if key is not None else value


def _format_cache_state(value: LyricsCacheState, translator: Translator) -> str:
    """Format whether the visible document came from or was saved into cache."""
    keys = {
        LyricsCacheState.NONE: "search.cache.none",
        LyricsCacheState.FROM_CACHE: "search.cache.from",
        LyricsCacheState.MANUAL: "search.cache.manual",
    }
    return translator.text(keys[value])


__all__ = ["LyricsStatusBand"]
