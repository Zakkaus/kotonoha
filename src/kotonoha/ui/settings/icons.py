"""Icon-picker page and icon selection behavior for the settings dialog."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QLabel,
    QListView,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import leaf_icon
from ...config import DEFAULT_ICON_NAME, Config
from ...strings import Translator
from ...tray import discover_icon_paths
from .controls import SettingsWidgets
from .widgets import IconStrip, no_tint_icon

if TYPE_CHECKING:
    from .dialog import SettingsDialog


class SettingsIconPageBuilder:
    """Own the icon page, preview refresh, and icon picker controls."""

    def __init__(self, dialog: SettingsDialog, widgets: SettingsWidgets, *, translator: Translator) -> None:
        self._dialog = dialog
        self._widgets = widgets
        self._translator = translator

    @property
    def _config(self) -> Config:
        return self._dialog.staged_config

    def build(self) -> QWidget:
        """Build the tray and window icon pickers."""
        t = self._translator.text
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(0)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        outer.addLayout(form)
        outer.addStretch(1)

        self._widgets.tray_icon_list = self.build_icon_picker(self._config.icon_name)
        form.addRow(QLabel(t("set.tray_icon")))
        form.addRow(self._widgets.tray_icon_list)
        form.addRow(self._hint(t("set.tray_icon_hint")))

        self._widgets.window_icon_list = self.build_icon_picker(self._config.window_icon_name)
        form.addRow(QLabel(t("set.window_icon")))
        form.addRow(self._widgets.window_icon_list)
        form.addRow(self._hint(t("set.window_icon_hint")))
        return page

    def refresh_generated_icons(self) -> None:
        """Re-render generated icon previews after the accent is applied."""
        dark = self._dialog.theme_name == "dark"
        for _icon_list, items in self._widgets.icon_pickers:
            for key in leaf_icon.PICKER_STYLES:
                item = items.get(key)
                if item is not None:
                    pixmap = leaf_icon.render_leaf(
                        key,
                        self._config.accent_start,
                        dark_panel=dark,
                        size=64,
                    )
                    item.setIcon(no_tint_icon(pixmap))

    def build_icon_picker(self, selected_key: str) -> IconStrip:
        """Build one independently selectable icon strip."""
        icon_list = IconStrip()
        icon_list.setObjectName("iconPicker")
        icon_list.setViewMode(QListView.ViewMode.IconMode)
        icon_list.setFlow(QListView.Flow.LeftToRight)
        icon_list.setMovement(QListView.Movement.Static)
        icon_list.setResizeMode(QListView.ResizeMode.Adjust)
        icon_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        icon_list.setWrapping(True)
        icon_list.setIconSize(QSize(40, 40))
        icon_list.setGridSize(QSize(54, 54))
        icon_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        icon_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        items: dict[str, QListWidgetItem] = {}
        selected_item: QListWidgetItem | None = None
        default_item: QListWidgetItem | None = None

        def add(key: str, pixmap: QPixmap) -> QListWidgetItem:
            item = QListWidgetItem(no_tint_icon(pixmap), "")
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_list.addItem(item)
            items[key] = item
            return item

        dark = self._dialog.theme_name == "dark"
        offered = leaf_icon.PICKER_STYLES
        if leaf_icon.is_generated(selected_key) and selected_key not in offered:
            offered = (*offered, selected_key)
        for key in offered:
            item = add(
                key,
                leaf_icon.render_leaf(key, self._config.accent_start, dark_panel=dark, size=64),
            )
            if key == selected_key:
                selected_item = item
        for choice in discover_icon_paths():
            source = QIcon(str(choice.path))
            if source.isNull():
                continue
            item = add(choice.key, source.pixmap(QSize(64, 64)))
            if choice.key == selected_key:
                selected_item = item
            if choice.key == DEFAULT_ICON_NAME:
                default_item = item
        icon_list.setCurrentItem(selected_item or default_item)
        self._widgets.icon_pickers.append((icon_list, items))
        return icon_list

    def _hint(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("hint")
        label.setWordWrap(True)
        return label


def selected_icon_name(icon_list: IconStrip) -> str:
    """Return the selected icon key, falling back to the default icon."""
    item = icon_list.currentItem()
    return str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else DEFAULT_ICON_NAME


__all__ = ["SettingsIconPageBuilder", "selected_icon_name"]
