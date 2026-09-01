"""Themed window for searching and explicitly applying lyric candidates."""

from __future__ import annotations

from PyQt6.QtCore import QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ... import leaf_icon
from ...app.intents import SearchLyrics, SelectLyrics
from ...config import Config
from ...display.models import LyricsDisplayStatus
from ...icons import search_icon
from ...lyrics.cache import CacheWriteResult, CacheWriteStatus
from ...lyrics.search import LyricsSearchQuery, LyricsSearchResponse, LyricsSearchResult
from ...platform import OverlayPlatformFactory
from ...strings import Translator
from . import theme
from .lyrics_search_model import (
    LyricsSearchTableModel,
    format_duration,
    format_unavailable_details,
    format_unavailable_sources,
)
from .lyrics_status import LyricsStatusBand
from .surface import SettingsTitleBar, ThemedSettingsDialog
from .widgets import ElidingLabel


class LyricsSearchDialog(ThemedSettingsDialog):
    """Search configured lyric providers and apply one selected result."""

    intent_requested = pyqtSignal(object)

    def __init__(
        self,
        config: Config,
        query: LyricsSearchQuery,
        parent: QWidget | None = None,
        *,
        status: LyricsDisplayStatus | None = None,
        translator: Translator | None = None,
        platform_factory: OverlayPlatformFactory | None = None,
    ) -> None:
        super().__init__(config, parent, platform_factory=platform_factory)
        self._translator = translator if translator is not None else Translator(config.ui_language)
        self._current_query = query
        self._results: tuple[LyricsSearchResult, ...] = ()
        self._busy = False
        self._current_status = status if status is not None else LyricsDisplayStatus()

        self.setObjectName("lyricsSearchDialog")
        self.setWindowTitle(self._translator.text("search.title"))
        self.setMinimumSize(820, 540)
        self.resize(1060, 700)
        self._apply_surface_style()
        self._mark_surface_style_ready()

        self._model = LyricsSearchTableModel(self._translator)
        self._title_edit = self._query_edit("search.placeholder.title", query.title)
        self._artist_edit = self._query_edit("search.placeholder.artist", query.artist)
        self._album_edit = self._query_edit("search.placeholder.album", query.album)
        for editor in (self._title_edit, self._artist_edit, self._album_edit):
            editor.returnPressed.connect(self._request_search)

        self._search_button = QPushButton(self._translator.text("btn.search_lyrics"))
        self._search_button.setObjectName("searchButton")
        self._search_button.setIcon(search_icon("#FFFFFF" if self._theme == "dark" else "#303136"))
        self._search_button.clicked.connect(self._request_search)

        self._table = QTableView()
        self._table.setObjectName("lyricsSearchTable")
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)
        self._table.setTextElideMode(Qt.TextElideMode.ElideRight)
        table_viewport = self._table.viewport()
        if table_viewport is not None:
            table_viewport.setAutoFillBackground(False)
        vertical_header = self._table.verticalHeader()
        if vertical_header is not None:
            vertical_header.setVisible(False)
        horizontal_header = self._table.horizontalHeader()
        if horizontal_header is not None:
            horizontal_header.setAutoFillBackground(False)
            horizontal_header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            horizontal_header.setStretchLastSection(False)
            horizontal_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            for section in (1, 2, 3):
                horizontal_header.setSectionResizeMode(section, QHeaderView.ResizeMode.Stretch)
            for section in (4, 5, 6):
                horizontal_header.setSectionResizeMode(section, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._table.doubleClicked.connect(self._request_apply_for_index)
        selection_model = self._table.selectionModel()
        if selection_model is None:
            raise RuntimeError("lyrics search table selection model is unavailable")
        selection_model.selectionChanged.connect(self._update_action_state)

        self._status = ElidingLabel()
        self._status.setObjectName("searchStatus")
        self._apply_button = QPushButton(self._translator.text("btn.apply_lyrics"))
        self._apply_button.setObjectName("applyButton")
        self._apply_button.clicked.connect(self._request_apply)
        close_button = QPushButton(self._translator.text("btn.close"))
        close_button.clicked.connect(self.close)
        for button in (self._search_button, self._apply_button, close_button):
            button.setAutoDefault(False)
        close_button.setObjectName("dialogCloseButton")
        subtitle = QLabel(self._translator.text("search.subtitle"))
        subtitle.setObjectName("hint")
        subtitle.setWordWrap(True)
        current_meta = self._current_metadata(query)
        self._status_band = LyricsStatusBand(self._current_status, self._translator, self)
        query_form = self._query_form()
        header_line = QWidget()
        header_line.setObjectName("navDivider")
        header_line.setFixedHeight(1)
        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addWidget(self._status, 1)
        footer.addWidget(self._apply_button)
        footer.addWidget(close_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        layout.addWidget(self._title_bar())
        layout.addWidget(header_line)
        layout.addWidget(subtitle)
        layout.addWidget(current_meta)
        layout.addWidget(self._status_band)
        layout.addWidget(query_form)
        layout.addWidget(self._table, 1)
        layout.addLayout(footer)
        self._update_action_state()

    def _apply_surface_style(self) -> None:
        """Apply the shared settings skin plus result-window surface rules."""
        self.setStyleSheet(self._style_sheet())

    def _title_bar(self) -> QWidget:
        """Build the shared draggable title bar with the application mark."""
        title_bar = SettingsTitleBar()
        bar = QHBoxLayout(title_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(9)
        logo_badge = QLabel()
        logo_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        pixmap = leaf_icon.render_leaf(leaf_icon.ACCENT, self._accent, size=44)
        pixmap.setDevicePixelRatio(2.0)
        logo_badge.setPixmap(pixmap)
        bar.addWidget(logo_badge)
        title = QLabel(self._translator.text("search.title"))
        title.setObjectName("dialogTitle")
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        close_button = QPushButton("✕")
        close_button.setObjectName("closeButton")
        close_button.setAutoDefault(False)
        close_button.setFixedSize(26, 26)
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.clicked.connect(self.close)
        bar.addWidget(title)
        bar.addStretch(1)
        bar.addWidget(close_button)
        return title_bar

    def _current_metadata(self, query: LyricsSearchQuery) -> QFrame:
        """Build the read-only current-track metadata band."""
        frame = QFrame()
        frame.setObjectName("trackMeta")
        grid = QGridLayout(frame)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        heading = QLabel(self._translator.text("search.current_track"))
        heading.setObjectName("sectionTitle")
        grid.addWidget(heading, 0, 0, 1, 4)
        values = (
            ("search.meta.title", query.title),
            ("search.meta.artist", query.artist),
            ("search.meta.album", query.album),
            ("search.meta.duration", format_duration(query.duration_s, self._translator)),
        )
        for column, (key, value) in enumerate(values):
            label = QLabel(self._translator.text(key))
            label.setObjectName("metaLabel")
            content = QLabel(value or "-")
            content.setObjectName("metaValue")
            content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            content.setWordWrap(False)
            grid.addWidget(label, 1, column)
            grid.addWidget(content, 2, column)
            grid.setColumnStretch(column, 1)
        return frame

    def _query_form(self) -> QWidget:
        """Build the editable title, artist, album, and search controls."""
        widget = QWidget()
        grid = QGridLayout(widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        heading = QLabel(self._translator.text("search.query"))
        heading.setObjectName("sectionTitle")
        grid.addWidget(heading, 0, 0, 1, 5)
        fields = (
            ("search.query_title", self._title_edit),
            ("search.query_artist", self._artist_edit),
            ("search.query_album", self._album_edit),
        )
        for column, (key, editor) in enumerate(fields):
            label = QLabel(self._translator.text(key))
            label.setObjectName("fieldLabel")
            grid.addWidget(label, 1, column * 2)
            grid.addWidget(editor, 2, column * 2, 1, 2)
        grid.addWidget(self._search_button, 2, 6)
        return widget

    def _query_edit(self, placeholder_key: str, value: str) -> QLineEdit:
        """Create one bounded, editable search field."""
        editor = QLineEdit(value)
        editor.setObjectName("queryField")
        editor.setPlaceholderText(self._translator.text(placeholder_key))
        editor.setClearButtonEnabled(True)
        return editor

    def show(self) -> None:
        """Show the prefilled search window without triggering an implicit query."""
        super().show()
        self._title_edit.setFocus()
        self._title_edit.selectAll()

    def set_results(self, query: LyricsSearchQuery, response: LyricsSearchResponse) -> None:
        """Display all provider candidates returned for the latest query."""
        self._current_query = query
        self._results = response.results
        self._model.set_results(response.results)
        unavailable = format_unavailable_sources(response.unavailable_sources, self._translator)
        detail = format_unavailable_details(response.unavailable_sources, self._translator)
        if response.results and response.unavailable_sources:
            message = self._translator.text("search.partial_results").format(
                count=len(response.results), sources=unavailable
            )
        elif response.results:
            message = self._translator.text("search.results").format(count=len(response.results))
        elif response.unavailable_sources:
            message = self._translator.text("search.partial_results").format(
                count=0, sources=unavailable
            )
        else:
            message = self._translator.text("search.no_results")
        self._show_status(message, detail)
        self._update_action_state()

    def set_current_status(self, status: LyricsDisplayStatus) -> None:
        """Refresh the active lyric source after a selection is applied."""
        self._current_status = status
        self._status_band.set_status(status)

    def set_busy(self, busy: bool) -> None:
        """Disable query and selection commands while an owned task is active."""
        self._busy = busy
        for editor in (self._title_edit, self._artist_edit, self._album_edit):
            editor.setEnabled(not busy)
        self._search_button.setEnabled(not busy)
        self._table.setEnabled(not busy)
        self._update_action_state()
        if busy:
            self._show_status(self._translator.text("search.loading"))

    def show_error(self, message: str) -> None:
        """Show a failed search or cache-write operation without discarding rows."""
        self._status.setObjectName("searchError")
        self._status.setText(message)
        self._refresh_status_style()

    def show_apply_result(self, result: CacheWriteResult, displayed: bool) -> None:
        """Show the cache outcome and whether the active display changed immediately."""
        key = "search.apply.created" if result.status is CacheWriteStatus.CREATED else "search.apply.updated"
        message = self._translator.text(key)
        if not displayed:
            message = f"{message} {self._translator.text('search.apply.next_track')}"
        self._show_status(message)

    def _request_search(self) -> None:
        """Publish one editable provider-search query."""
        if self._busy:
            return
        query = LyricsSearchQuery(
            self._title_edit.text(),
            self._artist_edit.text(),
            self._album_edit.text(),
            self._current_query.duration_s,
        )
        self.intent_requested.emit(SearchLyrics(query))

    def _request_apply(self) -> None:
        """Publish the currently selected result for explicit cache persistence."""
        if self._busy:
            return
        selection_model = self._table.selectionModel()
        if selection_model is None:
            return
        rows = selection_model.selectedRows()
        if not rows:
            return
        result = self._model.result_at(rows[0].row())
        if result is not None:
            self.intent_requested.emit(SelectLyrics(result))

    def _request_apply_for_index(self, index: QModelIndex) -> None:
        """Apply the row activated by a double-click."""
        if not self._busy:
            self._table.selectRow(index.row())
            self._request_apply()

    def _update_action_state(self, *_args: object) -> None:
        """Keep the apply action aligned with current selection and task state."""
        selection_model = self._table.selectionModel()
        has_selection = selection_model is not None and bool(selection_model.selectedRows())
        self._apply_button.setEnabled(not self._busy and has_selection)

    def _show_status(self, message: str, detail: str = "") -> None:
        """Render a status message, keeping any longer explanation in its tooltip."""
        self._status.setObjectName("searchStatus")
        self._status.setText(message)
        # The line elides, so the per-source reasons have to stay reachable.
        self._status.setToolTip(detail)
        self._refresh_status_style()

    def _refresh_status_style(self) -> None:
        """Reapply the status label selector after changing its object name."""
        status_style = self._status.style()
        if status_style is not None:
            status_style.unpolish(self._status)
            status_style.polish(self._status)

    def _style_sheet(self) -> str:
        """Extend the shared theme with the track band and dense result table."""
        palette = theme._PALETTES[self._theme]
        card_background = theme._card_background(self._theme, self._frosted, self._win_opacity)
        accent = QColor(self._accent)
        accent_soft = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, 42)"
        return theme._skin(self._accent, self._theme, self._frosted, self._win_opacity) + f"""
QDialog#lyricsSearchDialog {{ background: transparent; }}
QFrame#trackMeta,
QFrame#lyricsStatus {{
    background: {card_background};
    border: 1px solid {palette["CARD_BORDER"]};
    border-radius: 10px;
}}
QLabel#sectionTitle {{ color: {palette["TEXT_STRONG"]}; font-weight: 600; }}
QLabel#fieldLabel, QLabel#metaLabel {{ color: {palette["TEXT_DIM"]}; }}
QLabel#metaValue {{ color: {palette["TEXT_STRONG"]}; font-weight: 600; }}
QTableView#lyricsSearchTable,
QTableView#lyricsSearchTable > QWidget#qt_scrollarea_viewport {{
    background: {palette["LIST_BG"]};
    border: 1px solid {palette["LIST_BORDER"]};
    border-radius: 10px;
    color: {palette["TEXT"]};
    outline: none;
    selection-background-color: {accent_soft};
    selection-color: {palette["TEXT_STRONG"]};
    alternate-background-color: {palette["FIELD_BG"]};
}}
QTableView#lyricsSearchTable::item {{ padding: 7px 8px; border: none; }}
QHeaderView::section {{
    background: {palette["FIELD_BG"]};
    color: {palette["TEXT_DIM"]};
    border: none;
    border-bottom: 1px solid {palette["FIELD_BORDER"]};
    padding: 8px;
    font-weight: 600;
}}
QHeaderView {{ background: transparent; }}
QPushButton#applyButton {{ background: {self._accent}; color: #FFFFFF; border-color: {self._accent}; }}
QPushButton#applyButton:hover {{ background: {self._accent}; border-color: {self._accent}; }}
QLabel#searchError {{ color: #E56B6F; }}
"""

__all__ = ["LyricsSearchDialog"]
