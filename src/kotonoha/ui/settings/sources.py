"""Source-selection page and its local interactions."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...config import VALID_DISPLAY_SOURCES, VALID_LYRICS_SOURCES, Config
from ...strings import Translator
from .controls import SettingsWidgets
from .widgets import elide_player_row

if TYPE_CHECKING:
    from .dialog import SettingsDialog


class SettingsSourcesPageBuilder:
    """Own the player/source controls and source-specific signal handlers."""

    def __init__(
        self,
        dialog: SettingsDialog,
        widgets: SettingsWidgets,
        *,
        on_clear_cache: Callable[[], None],
        on_manage_cache: Callable[[], None],
        translator: Translator,
    ) -> None:
        self._dialog = dialog
        self._widgets = widgets
        self._on_clear_cache = on_clear_cache
        self._on_manage_cache = on_manage_cache
        self._translator = translator
        self._connect_signals()

    def _connect_signals(self) -> None:
        """Connect source controls once; rebuilding a page must not duplicate commands."""
        self._widgets.sources_list.itemChanged.connect(self.keep_one_source_checked)
        self._widgets.display_sources_list.itemChanged.connect(self.keep_one_display_source_checked)
        self._widgets.manage_cache.clicked.connect(self.emit_manage_cache)
        self._widgets.clear_cache.clicked.connect(self.emit_clear_cache)

    @property
    def _config(self) -> Config:
        return self._dialog.staged_config

    def build(self) -> QWidget:
        """Build player selection, source ordering, cache, and token controls."""
        t = self._translator.text
        d = self._dialog
        w = self._widgets
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(self._hint(t("set.sources_hint")))

        w.player_combo.clear()
        w.player_combo.setMinimumContentsLength(24)
        w.player_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        w.player_combo.addItem(t("player.auto"), "")
        offered = {player.bus_name for player in d.players}
        for player in d.players:
            status_key = f"player.status.{(player.playback_status or '').lower()}"
            status = t(status_key) if status_key != "player.status." else ""
            parts = [player.identity or player.bus_name, status or t("player.status.unknown")]
            if player.title:
                track = player.title
                if player.artist:
                    track += t("player.track_artist").format(artist=player.artist)
                parts.append(track)
            if player.automatic:
                parts.insert(0, t("player.automatic"))
            w.player_combo.addItem(elide_player_row(" · ".join(parts)), player.bus_name)
        if self._config.player_lock and self._config.player_lock not in offered:
            w.player_combo.addItem(self._config.player_lock + t("player.unavailable"), self._config.player_lock)
        player_index = w.player_combo.findData(self._config.player_lock)
        w.player_combo.setCurrentIndex(player_index if player_index >= 0 else 0)
        layout.addWidget(QLabel(t("set.player")))
        layout.addWidget(w.player_combo)
        layout.addWidget(self._hint(t("set.player_hint")))

        w.sources_list.clear()
        w.sources_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        enabled = self._config.lyrics_sources
        ordered = enabled + [source for source in VALID_LYRICS_SOURCES if source not in enabled]
        for source in ordered:
            item = QListWidgetItem(t(f"src.{source}"))
            item.setData(Qt.ItemDataRole.UserRole, source)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if source in enabled else Qt.CheckState.Unchecked)
            w.sources_list.addItem(item)
        self.keep_one_source_checked()
        layout.addWidget(QLabel(t("set.lyrics_sources")))
        layout.addWidget(w.sources_list)

        w.display_sources_list.clear()
        w.display_sources_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        display_enabled = self._config.display_sources
        display_ordered = display_enabled + [
            source for source in VALID_DISPLAY_SOURCES if source not in display_enabled
        ]
        for source in display_ordered:
            item = QListWidgetItem(t(f"src.display.{source}"))
            item.setData(Qt.ItemDataRole.UserRole, source)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if source in display_enabled else Qt.CheckState.Unchecked
            )
            w.display_sources_list.addItem(item)
        self.keep_one_display_source_checked()
        layout.addWidget(QLabel(t("set.display_sources")))
        layout.addWidget(self._hint(t("set.display_sources_hint")))
        layout.addWidget(w.display_sources_list)

        w.prefer_best.setText(t("set.prefer_best"))
        w.prefer_best.setChecked(self._config.prefer_best_lyrics)
        layout.addWidget(w.prefer_best)
        layout.addWidget(self._hint(t("set.prefer_best_hint")))
        w.fuzzy_match.setText(t("set.fuzzy_match"))
        w.fuzzy_match.setChecked(self._config.fuzzy_match)
        layout.addWidget(w.fuzzy_match)
        layout.addWidget(self._hint(t("set.fuzzy_match_hint")))
        w.cache_enabled.setText(t("set.cache_enabled"))
        w.cache_enabled.setChecked(self._config.cache_enabled)
        layout.addWidget(w.cache_enabled)
        w.manage_cache.setText(t("btn.manage_cache"))
        layout.addWidget(w.manage_cache)

        w.cider_token.setEchoMode(QLineEdit.EchoMode.Password)
        w.cider_token.setClearButtonEnabled(True)
        w.cider_token.setText(self._config.cider_api_token)
        layout.addWidget(QLabel(t("set.cider_token")))
        layout.addWidget(w.cider_token)
        layout.addWidget(self._hint(t("set.cider_token_hint")))
        w.clear_cache.setText(t("btn.clear_cache"))
        layout.addWidget(w.clear_cache)
        return page

    def emit_clear_cache(self, _checked: bool = False) -> None:
        """Submit the source page's clear-cache command to its owner."""
        del _checked
        self._on_clear_cache()

    def emit_manage_cache(self, _checked: bool = False) -> None:
        """Open the independent cache-management window through the owner."""
        del _checked
        self._on_manage_cache()

    def keep_one_source_checked(self, _item: QListWidgetItem | None = None) -> None:
        """Ensure the staged configuration always has one enabled source."""
        self._keep_one_source_checked(self._widgets.sources_list)

    def selected_sources(self) -> list[str]:
        """Return checked source identifiers in their current list order."""
        return self._selected_from(self._widgets.sources_list)

    def selected_display_sources(self) -> list[str]:
        """Return checked display source identifiers in their current list order."""
        return self._selected_from(self._widgets.display_sources_list)

    def keep_one_display_source_checked(self, _item: QListWidgetItem | None = None) -> None:
        """Ensure the staged configuration always has one display source."""
        self._keep_one_source_checked(self._widgets.display_sources_list)

    @staticmethod
    def _selected_from(source_list: QListWidget) -> list[str]:
        """Read checked identifiers from one ordered source list."""
        sources: list[str] = []
        for i in range(source_list.count()):
            item = source_list.item(i)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                sources.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return sources

    @staticmethod
    def _keep_one_source_checked(source_list: QListWidget) -> None:
        """Check the first row when a source list would otherwise be empty."""
        rows = [source_list.item(i) for i in range(source_list.count())]
        if any(row is not None and row.checkState() == Qt.CheckState.Checked for row in rows):
            return
        first = next((row for row in rows if row is not None), None)
        if first is None:
            return
        blocked = source_list.signalsBlocked()
        source_list.blockSignals(True)
        try:
            first.setCheckState(Qt.CheckState.Checked)
        finally:
            source_list.blockSignals(blocked)

    def _hint(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("hint")
        label.setWordWrap(True)
        return label


__all__ = ["SettingsSourcesPageBuilder"]
