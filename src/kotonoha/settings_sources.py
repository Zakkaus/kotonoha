"""Source-selection page and its local interactions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .config import VALID_LYRICS_SOURCES, Config
from .settings_widgets import elide_player_row
from .strings import t

if TYPE_CHECKING:
    from .settings_dialog import SettingsDialog


class SettingsSourcesPageBuilder:
    """Own the player/source controls and source-specific signal handlers."""

    def __init__(self, dialog: SettingsDialog) -> None:
        self._dialog = dialog

    @property
    def _config(self) -> Config:
        return self._dialog._config

    def build(self) -> QWidget:
        """Build player selection, source ordering, cache, and token controls."""
        d = self._dialog
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(self._hint(t("set.sources_hint")))

        d._player_combo = QComboBox()
        d._player_combo.setMinimumContentsLength(24)
        d._player_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        d._player_combo.addItem(t("player.auto"), "")
        offered = {player.bus_name for player in d._players}
        for player in d._players:
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
            d._player_combo.addItem(elide_player_row(" · ".join(parts)), player.bus_name)
        if self._config.player_lock and self._config.player_lock not in offered:
            d._player_combo.addItem(self._config.player_lock + t("player.unavailable"), self._config.player_lock)
        player_index = d._player_combo.findData(self._config.player_lock)
        d._player_combo.setCurrentIndex(player_index if player_index >= 0 else 0)
        layout.addWidget(QLabel(t("set.player")))
        layout.addWidget(d._player_combo)
        layout.addWidget(self._hint(t("set.player_hint")))

        d._sources_list = QListWidget()
        d._sources_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        enabled = self._config.lyrics_sources
        ordered = enabled + [source for source in VALID_LYRICS_SOURCES if source not in enabled]
        for source in ordered:
            item = QListWidgetItem(t(f"src.{source}"))
            item.setData(Qt.ItemDataRole.UserRole, source)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if source in enabled else Qt.CheckState.Unchecked)
            d._sources_list.addItem(item)
        d._sources_list.itemChanged.connect(self.keep_one_source_checked)
        self.keep_one_source_checked()
        layout.addWidget(d._sources_list)

        d._prefer_best = QCheckBox(t("set.prefer_best"))
        d._prefer_best.setChecked(self._config.prefer_best_lyrics)
        layout.addWidget(d._prefer_best)
        layout.addWidget(self._hint(t("set.prefer_best_hint")))
        d._fuzzy_match = QCheckBox(t("set.fuzzy_match"))
        d._fuzzy_match.setChecked(self._config.fuzzy_match)
        layout.addWidget(d._fuzzy_match)
        layout.addWidget(self._hint(t("set.fuzzy_match_hint")))
        d._cache_enabled = QCheckBox(t("set.cache_enabled"))
        d._cache_enabled.setChecked(self._config.cache_enabled)
        layout.addWidget(d._cache_enabled)

        d._cider_token = QLineEdit()
        d._cider_token.setEchoMode(QLineEdit.EchoMode.Password)
        d._cider_token.setClearButtonEnabled(True)
        d._cider_token.setText(self._config.cider_api_token)
        layout.addWidget(QLabel(t("set.cider_token")))
        layout.addWidget(d._cider_token)
        layout.addWidget(self._hint(t("set.cider_token_hint")))
        d._clear_cache = QPushButton(t("btn.clear_cache"))
        d._clear_cache.clicked.connect(self.emit_clear_cache)
        layout.addWidget(d._clear_cache)
        return page

    def emit_clear_cache(self, _checked: bool = False) -> None:
        """Forward the clear-cache action to the dialog's application signal."""
        self._dialog.clear_cache_requested.emit()

    def keep_one_source_checked(self, _item: QListWidgetItem | None = None) -> None:
        """Ensure the staged configuration always has one enabled source."""
        source_list = self._dialog._sources_list
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

    def selected_sources(self) -> list[str]:
        """Return checked source identifiers in their current list order."""
        source_list = self._dialog._sources_list
        sources: list[str] = []
        for i in range(source_list.count()):
            item = source_list.item(i)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                sources.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return sources

    def _hint(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("hint")
        label.setWordWrap(True)
        return label


__all__ = ["SettingsSourcesPageBuilder"]
