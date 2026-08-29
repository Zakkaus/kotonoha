"""Reusable Qt widgets and presentation helpers for the settings pages."""

from __future__ import annotations

from PyQt6.QtCore import QModelIndex, Qt
from PyQt6.QtGui import QFont, QFontDatabase, QIcon, QPixmap, QResizeEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QFontComboBox,
    QListWidget,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

FONT_FALLBACKS = (
    "Noto Sans CJK SC", "Noto Sans CJK TC", "Noto Sans CJK JP", "Source Han Sans SC",
    "Microsoft YaHei", "PingFang SC", "Noto Sans", "DejaVu Sans",
)
PLAYER_ROW_MAX_CHARS = 60


def elide_player_row(text: str) -> str:
    """Keep a player summary compact enough for the settings combo box."""
    return text if len(text) <= PLAYER_ROW_MAX_CHARS else text[: PLAYER_ROW_MAX_CHARS - 1] + "..."


class FontNameDelegate(QStyledItemDelegate):
    """Preview each font family in its own face in the combo popup."""

    def initStyleOption(self, option: QStyleOptionViewItem | None, index: QModelIndex) -> None:
        super().initStyleOption(option, index)
        if option is None:
            return
        family = index.data()
        if isinstance(family, str) and family:
            option.font = QFont(family)


def _constrain_combo_popup(combo: QComboBox) -> None:
    """Keep a content-sized Qt popup within its owning combo-box width."""
    view = combo.view()
    if view is None:
        return
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.setTextElideMode(Qt.TextElideMode.ElideRight)
    width = combo.width()
    view.setFixedWidth(width)
    popup = view.window()
    if popup is not None and popup is not view:
        popup.setFixedWidth(width)


class SettingsComboBox(QComboBox):
    """Combo box whose popup follows the stable width of its field."""

    def showPopup(self) -> None:
        """Open the native popup, then constrain its content-sized frame."""
        super().showPopup()
        _constrain_combo_popup(self)


class SettingsFontComboBox(QFontComboBox):
    """Font picker with the same bounded popup policy as other settings combos."""

    def showPopup(self) -> None:
        """Open the font list, then constrain its content-sized frame."""
        super().showPopup()
        _constrain_combo_popup(self)


class IconStrip(QListWidget):
    """Icon grid whose height follows the rows produced by Qt's layout."""

    def resizeEvent(self, e: QResizeEvent | None) -> None:
        super().resizeEvent(e)
        self._refit_height()

    def _refit_height(self) -> None:
        if self.count() == 0:
            return
        last = self.visualItemRect(self.item(self.count() - 1))
        wanted = last.bottom() + 8
        if self.height() != wanted:
            self.setFixedHeight(wanted)


def resolve_font_family(font_family: str) -> str:
    """Choose the first installed family from a configured fallback chain."""
    installed = set(QFontDatabase.families())
    requested = [name.strip().strip("'\"") for name in font_family.split(",")]
    for name in requested:
        if name and name in installed:
            return name
    for fallback in FONT_FALLBACKS:
        if fallback in installed:
            return fallback
    return next((name for name in requested if name), "")


def available_font_styles(family: str) -> list[str]:
    """Return the real styles advertised by one installed family."""
    styles = QFontDatabase.styles(family)
    if not styles:
        return ["Regular"]
    return sorted(styles, key=lambda style: (0 if style in ("Regular", "Book", "Normal") else 1, style))


def no_tint_icon(pixmap: QPixmap) -> QIcon:
    """Reuse the normal pixmap for selected states so Qt adds no blue tint."""
    icon = QIcon()
    for mode in (QIcon.Mode.Normal, QIcon.Mode.Selected, QIcon.Mode.Active):
        icon.addPixmap(pixmap, mode)
    return icon


__all__ = [
    "FONT_FALLBACKS",
    "FontNameDelegate",
    "IconStrip",
    "SettingsComboBox",
    "SettingsFontComboBox",
    "available_font_styles",
    "elide_player_row",
    "no_tint_icon",
    "resolve_font_family",
]
