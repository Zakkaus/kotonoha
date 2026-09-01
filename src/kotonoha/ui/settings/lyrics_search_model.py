"""Table model and display formatting for lyric search results."""

from __future__ import annotations

from collections.abc import Mapping

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PyQt6.QtGui import QColor

from ...lyrics.artifact import LyricsArtifact
from ...lyrics.match import MatchConfidence
from ...lyrics.search import LyricsSearchResult, LyricsSearchUnavailable, LyricsTiming, LyricsVersion
from ...lyrics.title_grammar import title_without_version_labels, version_labels
from ...strings import Translator

# Sorting must not use the displayed text: "High" sorts under "Medium", and
# "4:03" under "10:00". Each column publishes a comparable value on this role.
SORT_ROLE = Qt.ItemDataRole.UserRole
# The version qualifiers of a row's title, for the delegate that draws them.
VERSION_LABEL_ROLE = Qt.ItemDataRole.UserRole + 1
# The match rating's colour, for the delegate that draws it as a pill.
_TITLE_COLUMN = 1
# A qualifier is lifted out of the title only when it is short enough to read
# whole. Shortened to fit, a mark says less than the words it replaced.
_LIFTABLE_LABEL_CHARS = 8
_CONFIDENCE_RANK = {MatchConfidence.NONE: 0, MatchConfidence.MEDIUM: 1, MatchConfidence.HIGH: 2}
_DURATION_COLUMN = 4
_MATCH_COLUMN = 6


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

    def __init__(
        self,
        translator: Translator,
        confidence_colours: Mapping[MatchConfidence, str],
    ) -> None:
        super().__init__()
        self._translator = translator

        # Supplied by the owning dialog from its theme, so the table names no
        # colour of its own and the same rating reads on either surface.
        self._confidence_colours = confidence_colours
        self._results: tuple[LyricsSearchResult, ...] = ()

    def _liftable_labels(self, artifact: LyricsArtifact) -> tuple[str, ...]:
        """Return the qualifiers short enough to stand beside the title as marks."""
        labels = version_labels(artifact.title, artifact.artist)
        if any(len(label) > _LIFTABLE_LABEL_CHARS for label in labels):
            return ()
        return labels

    def _shown_title(self, artifact: LyricsArtifact) -> str:
        """Return the title without the qualifiers that are drawn beside it.

        A qualifier too long to lift stays where the publisher put it, so the row
        still says which version it is even though nothing is marked.
        """
        if not self._liftable_labels(artifact):
            return artifact.title
        return title_without_version_labels(artifact.title, artifact.artist)

    def set_confidence_colours(self, colours: Mapping[MatchConfidence, str]) -> None:
        """Adopt a new theme's rating colours without rebuilding the table."""
        self._confidence_colours = colours
        rows = self.rowCount()
        if rows:
            self.dataChanged.emit(self.index(0, 0), self.index(rows - 1, self.columnCount() - 1))

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
                self._shown_title(artifact),
                readable(artifact.artist),
                readable(artifact.album),
                format_duration(artifact.duration_s, self._translator),
                format_version(result.version, self._translator),
                format_confidence(result.confidence, self._translator),
            )
            return values[index.column()]
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == _MATCH_COLUMN:
            # The rating is one word; its colour is the whole of the emphasis.
            return QColor(self._confidence_colours[artifact.confidence])
        if role == VERSION_LABEL_ROLE:
            return self._liftable_labels(artifact) if index.column() == _TITLE_COLUMN else ()
        if role == SORT_ROLE:
            if index.column() == _DURATION_COLUMN:
                # An unknown length sorts below every known one rather than as zero.
                return artifact.duration_s if artifact.duration_s is not None else -1.0
            if index.column() == _MATCH_COLUMN:
                return _CONFIDENCE_RANK[artifact.confidence]
            value = self.data(index, Qt.ItemDataRole.DisplayRole)
            return value.casefold() if isinstance(value, str) else value
        if role == Qt.ItemDataRole.TextAlignmentRole:
            # Every column centres, headers included. Mixing left, right and centre
            # down one table gives each column its own edge and the rows read as
            # crooked, which is worse than the alignment each column would prefer.
            return Qt.AlignmentFlag.AlignCenter
        if role == Qt.ItemDataRole.ToolTipRole:
            return (
                f"{result.source_key}\n"
                f"{artifact.title} - {artifact.artist}\n"
                f"{format_duration(artifact.duration_s, self._translator)}\n"
                # The version column names the granularity, so the encoding lives here.
                f"{format_version_detail(result.version, self._translator)}"
            )
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        """Return translated table headers."""
        if orientation is not Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return self._translator.text(self._headers[section]) if 0 <= section < len(self._headers) else None

    def result_at(self, row: int) -> LyricsSearchResult | None:
        """Return the typed result currently represented by ``row``."""
        return self._results[row] if 0 <= row < len(self._results) else None


def format_duration(value: float | None, translator: Translator) -> str:
    """Format a duration the way a player shows it, so it reads against the track."""
    if value is None:
        return translator.text("search.current_duration_unknown")
    duration = max(0, round(value))
    minutes, seconds = divmod(duration, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


# YRC and KRC carry a timestamp per character; LRC times whole lines only.


def format_version(version: LyricsVersion, translator: Translator) -> str:
    """Name the timing granularity, which is what separates two versions in use."""
    if version.has_translation:
        return _granularity(version, translator) + translator.text("search.version.translation")
    return _granularity(version, translator)


_TIMING_KEYS = {
    LyricsTiming.WORD: "search.version.word",
    LyricsTiming.LINE: "search.version.line",
    LyricsTiming.NONE: "search.version.lyrics",
}


def _granularity(version: LyricsVersion, translator: Translator) -> str:
    """Name how finely the sheet is timed, without saying anything else about it."""
    return translator.text(_TIMING_KEYS[version.timing])


def format_version_detail(version: LyricsVersion, translator: Translator) -> str:
    """Name the encoding itself, which the granularity label deliberately hides."""
    key = f"search.version.{version.format_id}"
    label = translator.text(key)
    return version.format_id.upper() if label == key else label


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


class LyricsSearchSortModel(QSortFilterProxyModel):
    """Order and narrow the candidate rows without disturbing the search results.

    The provider order is the order results arrived in, which says nothing about
    which candidate fits. Sorting and the high-match filter are view state: the
    underlying result list is untouched, so clearing the filter restores it.
    """

    def __init__(self, model: LyricsSearchTableModel) -> None:
        super().__init__()
        self._model = model
        self._high_only = False
        self.setSourceModel(model)
        self.setSortRole(SORT_ROLE)

    @property
    def high_only(self) -> bool:
        """Return whether rows below a high match are currently hidden."""
        return self._high_only

    def set_high_only(self, high_only: bool) -> None:
        """Hide or restore every candidate the matcher did not rate a high match."""
        if high_only == self._high_only:
            return
        self._high_only = high_only
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        """Accept every row unless the reader asked for high matches only."""
        del source_parent
        if not self._high_only:
            return True
        result = self._model.result_at(source_row)
        return result is not None and result.artifact.confidence is MatchConfidence.HIGH

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        """Name the sorted column with its direction, next to the name itself.

        Qt draws its indicator against the section's right edge, which with centred
        headers leaves the arrow a column-width away from the word it qualifies.
        """
        value = super().headerData(section, orientation, role)
        sorted_here = (
            role == Qt.ItemDataRole.DisplayRole
            and orientation is Qt.Orientation.Horizontal
            and section == self.sortColumn()
            and isinstance(value, str)
        )
        if not sorted_here:
            return value
        mark = "\u25b4" if self.sortOrder() is Qt.SortOrder.AscendingOrder else "\u25be"
        return f"{value} {mark}"

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        """Re-sort, and tell the header its own text just changed.

        headerData() writes the direction mark into the sorted column's name, so
        the strings a view holds go stale on every sort. Qt refetches header data
        only when told to, and nothing else here tells it.
        """
        previous = self.sortColumn()
        super().sort(column, order)
        for index in sorted({section for section in (previous, column) if section >= 0}):
            self.headerDataChanged.emit(Qt.Orientation.Horizontal, index, index)

    def result_at(self, row: int) -> LyricsSearchResult | None:
        """Return the result shown at one visible row, through the current ordering."""
        return self._model.result_at(self.mapToSource(self.index(row, 0)).row())


def readable(text: str) -> str:
    """Drop a field that carries only unrepresentable characters.

    lrclib stores album names that are nothing but U+FFFD, the marker for a
    character that could not be decoded. Six replacement glyphs in a column read
    as a rendering failure of ours; an empty cell states what is actually known.
    """
    return "" if text and not text.strip("\ufffd \t") else text


def _source_label(source: str, translator: Translator) -> str:
    """Return the localized provider name, or the raw source when it has no entry."""
    key = f"src.{source}"
    label = translator.text(key)
    return source if label == key else label


def format_unavailable_sources(
    sources: tuple[LyricsSearchUnavailable, ...], translator: Translator
) -> str:
    """Render only the localized provider names, short enough for the status line."""
    return ", ".join(_source_label(unavailable.source, translator) for unavailable in sources)


def format_unavailable_details(
    sources: tuple[LyricsSearchUnavailable, ...], translator: Translator
) -> str:
    """Render one localized name and reason per line, for the status tooltip."""
    return "\n".join(
        translator.text("search.unavailable_source").format(
            source=_source_label(unavailable.source, translator),
            reason=translator.text(unavailable.reason_key),
        )
        for unavailable in sources
    )


__all__ = [
    "LyricsSearchSortModel",
    "LyricsSearchTableModel",
    "SORT_ROLE",
    "VERSION_LABEL_ROLE",
    "format_confidence",
    "format_duration",
    "format_version_detail",
    "format_unavailable_details",
    "format_unavailable_sources",
    "readable",
    "format_version",
]
