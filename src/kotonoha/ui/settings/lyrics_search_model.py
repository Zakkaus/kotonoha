"""Table model and display formatting for lyric search results."""

from __future__ import annotations

from datetime import timedelta

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt

from ...lyrics.match import MatchConfidence
from ...lyrics.search import LyricsSearchResult, LyricsSearchUnavailable, LyricsVersion
from ...strings import Translator


class LyricsSearchTableModel(QAbstractTableModel):
    """Present selectable provider results while retaining exact artifacts."""

    _headers = (
        "search.column.provider",
        "search.column.title",
        "search.column.artist",
        "search.column.album",
        "search.column.duration",
        "search.column.version",
        "search.column.match",
    )

    def __init__(self, translator: Translator) -> None:
        super().__init__()
        self._translator = translator
        self._results: tuple[LyricsSearchResult, ...] = ()

    def set_results(self, results: tuple[LyricsSearchResult, ...]) -> None:
        """Replace all visible candidates with one completed search response."""
        self.beginResetModel()
        self._results = results
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        """Return the number of visible candidates."""
        return 0 if parent is not None and parent.isValid() else len(self._results)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        """Return the fixed result metadata column count."""
        del parent
        return len(self._headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        """Return display, alignment, and tooltip data for one result cell."""
        if not index.isValid() or not 0 <= index.row() < len(self._results):
            return None
        result = self._results[index.row()]
        artifact = result.artifact
        if role == Qt.ItemDataRole.DisplayRole:
            values = (
                self._translator.text(f"src.{artifact.provider}"),
                artifact.title,
                artifact.artist,
                artifact.album,
                format_duration(artifact.duration_s, self._translator),
                format_version(result.version, self._translator),
                format_confidence(result.confidence, self._translator),
            )
            return values[index.column()]
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in (4, 6):
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.ToolTipRole:
            return (
                f"{result.source_key}\n"
                f"{artifact.title} - {artifact.artist}\n"
                f"{format_duration(artifact.duration_s, self._translator)}"
            )
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        """Return translated table headers."""
        if role != Qt.ItemDataRole.DisplayRole or orientation is not Qt.Orientation.Horizontal:
            return None
        return self._translator.text(self._headers[section]) if 0 <= section < len(self._headers) else None

    def result_at(self, row: int) -> LyricsSearchResult | None:
        """Return the typed result currently represented by ``row``."""
        return self._results[row] if 0 <= row < len(self._results) else None


def format_duration(value: float | None, translator: Translator) -> str:
    """Format provider duration metadata compactly for the result table."""
    if value is None:
        return translator.text("search.current_duration_unknown")
    duration = max(0, round(value))
    return str(timedelta(seconds=duration)) if duration >= 3600 else translator.text(
        "search.duration_seconds"
    ).format(value=duration)


def format_version(version: LyricsVersion, translator: Translator) -> str:
    """Format provider encoding and translation metadata for display."""
    key = f"search.version.{version.format_id}"
    text = translator.text(key)
    if text == key:
        text = translator.text("search.version.lyrics")
    if version.has_translation:
        text += translator.text("search.version.translation")
    return text


def format_confidence(value: MatchConfidence, translator: Translator) -> str:
    """Format the provider match confidence for the result table."""
    keys = {
        MatchConfidence.HIGH: "search.match.high",
        MatchConfidence.MEDIUM: "search.match.medium",
        MatchConfidence.NONE: "search.match.none",
    }
    key = keys[value]
    text = translator.text(key)
    return text if text != key else translator.text("search.match.none")


def format_unavailable_sources(
    sources: tuple[LyricsSearchUnavailable, ...], translator: Translator
) -> str:
    """Render localized provider names together with their unavailable reasons."""
    labels: list[str] = []
    for unavailable in sources:
        key = f"src.{unavailable.source}"
        label = translator.text(key)
        source_label = unavailable.source if label == key else label
        labels.append(
            translator.text("search.unavailable_source").format(
                source=source_label,
                reason=unavailable.reason,
            )
        )
    return ", ".join(labels)


__all__ = [
    "LyricsSearchTableModel",
    "format_confidence",
    "format_duration",
    "format_unavailable_sources",
    "format_version",
]
