"""Page construction and page-local interactions for :mod:`settings_dialog`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFontComboBox,
    QFormLayout,
    QLabel,
    QListView,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import leaf_icon
from .config import ACCENT_PRESETS, DEFAULT_ICON_NAME, LEAD_MS_LIMIT, Config
from .settings_sources import SettingsSourcesPageBuilder
from .settings_widgets import (
    FontNameDelegate,
    IconStrip,
    available_font_styles,
    no_tint_icon,
    resolve_font_family,
)
from .strings import UI_LANGUAGES, t
from .tray import discover_icon_paths

if TYPE_CHECKING:
    from .settings_dialog import SettingsDialog


class SettingsPageBuilder:
    """Own construction and local signal handlers for all settings pages.

    The dialog remains the owner of the widgets and staged configuration. This
    object only groups the page controls and the interactions that mutate those
    controls, keeping window chrome and commit behavior out of page code.
    """

    def __init__(self, dialog: SettingsDialog) -> None:
        self._dialog = dialog
        self._sources = SettingsSourcesPageBuilder(dialog)

    @property
    def _config(self) -> Config:
        return self._dialog._config

    def general_page(self) -> QWidget:
        """Build the language, theme, blur, and settings-opacity page."""
        d = self._dialog
        page, form = self._form_page()
        d._ui_language = QComboBox()
        for value, label in UI_LANGUAGES:
            d._ui_language.addItem(label, value)
        idx = d._ui_language.findData(self._config.ui_language.value)
        d._ui_language.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow(t("set.language"), d._ui_language)
        form.addRow(self._hint(t("set.language_hint")))

        d._theme_combo = QComboBox()
        for value, key in (("auto", "theme.auto"), ("light", "theme.light"), ("dark", "theme.dark")):
            d._theme_combo.addItem(t(key), value)
        theme_idx = d._theme_combo.findData(self._config.theme.value)
        d._theme_combo.setCurrentIndex(theme_idx if theme_idx >= 0 else 0)
        form.addRow(t("set.theme"), d._theme_combo)

        d._frost_window = QCheckBox(t("set.frost_window"))
        d._frost_window.setChecked(self._config.frost_window)
        d._frost_window.setEnabled(d._blur_capable)
        form.addRow(d._frost_window)
        reason_key = {
            "session": "set.frost_window.no_session",
            "bridge": "set.frost_window.no_bridge",
            "protocol": "set.frost_window.no_protocol",
            "build": "set.frost_window.no_build",
        }.get(d._blur_reason or "")
        form.addRow(self._hint(t(reason_key) if reason_key else t("set.frost_window_hint")))

        d._settings_opacity = self._spin(0, 100, round(self._config.settings_opacity * 100), " %")
        form.addRow(t("set.settings_opacity"), d._settings_opacity)

        d._restart_btn = QPushButton(t("btn.restart"))
        d._restart_btn.setVisible(False)
        d._restart_btn.clicked.connect(d._request_restart)
        form.addRow(d._restart_btn)
        d._ui_language.currentIndexChanged.connect(d._update_restart_hint)
        return page

    def icon_page(self) -> QWidget:
        """Build the independent tray and window icon pickers."""
        d = self._dialog
        page, form = self._form_page()
        d._tray_icon_list = self.build_icon_picker(self._config.icon_name)
        form.addRow(QLabel(t("set.tray_icon")))
        form.addRow(d._tray_icon_list)
        form.addRow(self._hint(t("set.tray_icon_hint")))

        d._window_icon_list = self.build_icon_picker(self._config.window_icon_name)
        form.addRow(QLabel(t("set.window_icon")))
        form.addRow(d._window_icon_list)
        form.addRow(self._hint(t("set.window_icon_hint")))
        return page

    def text_page(self) -> QWidget:
        """Build font-family, font-style, and size controls."""
        d = self._dialog
        page, form = self._form_page()
        d._font_family = QFontComboBox()
        d._font_family.setEditable(False)
        d._font_family.setIconSize(QSize(0, 0))
        d._font_family.setItemDelegate(FontNameDelegate(d._font_family))
        d._font_family_shown = resolve_font_family(self._config.font_family)
        d._font_family_configured = self._config.font_family
        d._font_family.setCurrentFont(QFont(d._font_family_shown))
        form.addRow(t("set.font_family"), d._font_family)

        d._font_style = QComboBox()
        self.rebuild_style_options(d._font_family.currentFont().family(), prefer=self._config.font_style)
        d._font_family.currentFontChanged.connect(self.on_font_family_changed)
        form.addRow(t("set.font_style"), d._font_style)

        d._font_size = self._spin(8, 120, self._config.font_size, " px")
        form.addRow(t("set.font_size"), d._font_size)
        d._context_font_size = self._spin(8, 120, self._config.context_font_size, " px")
        form.addRow(t("set.context_font_size"), d._context_font_size)
        d._translation_font_size = self._spin(8, 120, self._config.translation_font_size, " px")
        form.addRow(t("set.translation_font_size"), d._translation_font_size)
        return page

    def panel_page(self) -> QWidget:
        """Build panel style, width, opacity, and tint controls."""
        d = self._dialog
        page, form = self._form_page()
        d._panel = QComboBox()
        for label, value in (
            ("set.panel.pill", "pill"), ("set.panel.white", "white"),
            ("set.panel.frost", "frost"), ("set.panel.text", "text"),
        ):
            d._panel.addItem(t(label), value)
        panel_index = d._panel.findData(self._config.panel_style.value)
        d._panel.setCurrentIndex(panel_index if panel_index >= 0 else 0)
        form.addRow(t("set.panel_style"), d._panel)

        d._panel_width_mode = QComboBox()
        d._panel_width_mode.addItem(t("panelsize.fit"), "fit")
        d._panel_width_mode.addItem(t("panelsize.fixed"), "fixed")
        width_index = d._panel_width_mode.findData(self._config.panel_width_mode.value)
        d._panel_width_mode.setCurrentIndex(width_index if width_index >= 0 else 0)
        form.addRow(t("set.panel_size"), d._panel_width_mode)

        d._panel_width = self._spin(240, 2400, self._config.panel_width, " px")
        d._panel_width.setSingleStep(20)
        form.addRow(t("set.panel_width"), d._panel_width)
        form.addRow(self._hint(t("set.panel_size_hint")))
        d._panel_width_mode.currentIndexChanged.connect(self.update_panel_width_enabled)
        self.update_panel_width_enabled()

        d._panel_opacity = {"opacity": self._config.opacity, "frost_opacity": self._config.frost_opacity}
        d._opacity_active_key = self.opacity_key()
        d._opacity = self._spin(0, 100, round(d._panel_opacity[d._opacity_active_key] * 100), " %")
        form.addRow(t("set.opacity"), d._opacity)
        d._panel.currentIndexChanged.connect(self.on_panel_style_changed)

        d._panel_tint = QCheckBox(t("set.panel_tint"))
        d._panel_tint.setChecked(self._config.panel_accent_tint)
        form.addRow(d._panel_tint)
        form.addRow(self._hint(t("set.panel_hint")))
        return page

    def effects_page(self) -> QWidget:
        """Build accent and visual-effect controls."""
        d = self._dialog
        page, form = self._form_page()
        d._accent = QComboBox()
        d._custom_index = -1
        matched = False
        for key, start, end, sweep in ACCENT_PRESETS:
            d._accent.addItem(t(f"accent.{key}"), (start, end, sweep))
            if (start.lower(), end.lower(), sweep.lower()) == (
                self._config.accent_start.lower(), self._config.accent_end.lower(), self._config.accent_sweep.lower()
            ):
                d._accent.setCurrentIndex(d._accent.count() - 1)
                matched = True
        if not matched:
            self.set_custom_accent((self._config.accent_start, self._config.accent_end, self._config.accent_sweep))
        d._accent.addItem(t("set.accent.pick"), None)
        d._accent_last_index = d._accent.currentIndex()
        d._accent.activated.connect(self.on_accent_activated)
        form.addRow(t("set.accent"), d._accent)

        d._fx_animate = QCheckBox(t("set.fx_animate"))
        d._fx_animate.setChecked(self._config.fx_animate)
        form.addRow(d._fx_animate)
        d._fx_transition = QComboBox()
        for value, key in (
            ("fade", "fxtrans.fade"), ("rise", "fxtrans.rise"),
            ("slide", "fxtrans.slide"), ("zoom", "fxtrans.zoom"),
        ):
            d._fx_transition.addItem(t(key), value)
        trans_idx = d._fx_transition.findData(self._config.fx_transition.value)
        d._fx_transition.setCurrentIndex(trans_idx if trans_idx >= 0 else 1)
        form.addRow(t("set.fx_transition"), d._fx_transition)
        d._fx_glow = QCheckBox(t("set.fx_glow"))
        d._fx_glow.setChecked(self._config.fx_glow)
        form.addRow(d._fx_glow)
        d._fx_word_pop = QCheckBox(t("set.fx_word_pop"))
        d._fx_word_pop.setChecked(self._config.fx_word_pop)
        form.addRow(d._fx_word_pop)
        d._fx_intensity = QComboBox()
        for value, key in (("subtle", "fxintensity.subtle"), ("expressive", "fxintensity.expressive")):
            d._fx_intensity.addItem(t(key), value)
        fx_idx = d._fx_intensity.findData(self._config.fx_intensity.value)
        d._fx_intensity.setCurrentIndex(fx_idx if fx_idx >= 0 else 0)
        form.addRow(t("set.fx_intensity"), d._fx_intensity)
        return page

    def lyrics_page(self) -> QWidget:
        """Build lyric timing, translation, script, and interlude controls."""
        d = self._dialog
        page, form = self._form_page()
        d._karaoke = QCheckBox(t("set.karaoke"))
        d._karaoke.setChecked(self._config.karaoke)
        form.addRow(d._karaoke)
        d._lead = self._spin(-LEAD_MS_LIMIT, LEAD_MS_LIMIT, self._config.lead_ms, " ms")
        d._lead.setSingleStep(20)
        d._lead.setToolTip(t("set.lead.tip"))
        form.addRow(t("set.lead"), d._lead)
        d._translation = QCheckBox(t("set.show_translation"))
        d._translation.setChecked(self._config.show_translation)
        form.addRow(d._translation)
        d._current_line_only = QCheckBox(t("set.current_line_only"))
        d._current_line_only.setChecked(self._config.current_line_only)
        form.addRow(d._current_line_only)
        form.addRow(self._hint(t("set.current_line_only_hint")))

        d._lyrics_script = QComboBox()
        for value, key in (
            ("off", "lyricscript.off"), ("zh-Hans", "lyricscript.hans"),
            ("zh-Hant", "lyricscript.hant"),
        ):
            d._lyrics_script.addItem(t(key), value)
        script_idx = d._lyrics_script.findData(self._config.lyrics_script.value)
        d._lyrics_script.setCurrentIndex(script_idx if script_idx >= 0 else 0)
        form.addRow(t("set.lyrics_script"), d._lyrics_script)
        form.addRow(self._hint(t("set.lyrics_script_hint")))

        d._interlude_style = QComboBox()
        d._interlude_style.addItem(t("set.interlude.dots"), "dots")
        d._interlude_style.addItem(t("set.interlude.symbol"), "symbol")
        style_idx = d._interlude_style.findData(self._config.interlude_style.value)
        d._interlude_style.setCurrentIndex(style_idx if style_idx >= 0 else 0)
        form.addRow(t("set.interlude_style"), d._interlude_style)
        d._interlude_countdown = QComboBox()
        d._interlude_countdown.addItem(t("set.interlude.count_off"), "off")
        d._interlude_countdown.addItem(t("set.interlude.count_percent"), "percent")
        d._interlude_countdown.addItem(t("set.interlude.count_seconds"), "seconds")
        count_idx = d._interlude_countdown.findData(self._config.interlude_countdown.value)
        d._interlude_countdown.setCurrentIndex(count_idx if count_idx >= 0 else 0)
        form.addRow(t("set.interlude_countdown"), d._interlude_countdown)
        form.addRow(self._hint(t("set.interlude_hint")))
        return page

    def position_page(self) -> QWidget:
        """Build edge anchor, margin, and input-mode controls."""
        d = self._dialog
        page, form = self._form_page()
        d._anchor = QComboBox()
        d._anchor.addItem(t("set.top"), True)
        d._anchor.addItem(t("set.bottom"), False)
        d._anchor.setCurrentIndex(0 if self._config.anchor_top else 1)
        form.addRow(t("set.position"), d._anchor)
        d._margin_edge = self._spin(0, 4000, self._config.margin_edge, " px")
        form.addRow(t("set.margin_edge"), d._margin_edge)
        d._margin_x = self._spin(-2000, 2000, self._config.margin_x, " px")
        form.addRow(t("set.margin_x"), d._margin_x)
        d._passthrough = QCheckBox(t("set.passthrough"))
        d._passthrough.setChecked(self._config.passthrough)
        form.addRow(d._passthrough)
        form.addRow(self._hint(t("set.box_hint")))
        return page

    def sources_page(self) -> QWidget:
        """Build the source page through its dedicated page owner."""
        return self._sources.build()

    def refresh_generated_icons(self) -> None:
        """Re-render accent-dependent icon previews after Apply."""
        d = self._dialog
        dark = d._theme == "dark"
        for _list, items in d._icon_pickers:
            for key in leaf_icon.PICKER_STYLES:
                item = items.get(key)
                if item is not None:
                    pixmap = leaf_icon.render_leaf(key, d._config.accent_start, dark_panel=dark, size=64)
                    item.setIcon(no_tint_icon(pixmap))

    def build_icon_picker(self, selected_key: str) -> IconStrip:
        """Build one independently selectable icon strip."""
        d = self._dialog
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

        dark = d._theme == "dark"
        offered = leaf_icon.PICKER_STYLES
        if leaf_icon.is_generated(selected_key) and selected_key not in offered:
            offered = (*offered, selected_key)
        for key in offered:
            item = add(key, leaf_icon.render_leaf(key, d._config.accent_start, dark_panel=dark, size=64))
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
        d._icon_pickers.append((icon_list, items))
        return icon_list

    def set_custom_accent(self, triple: tuple[str, str, str]) -> None:
        """Show a picked accent in the reusable custom combo entry."""
        d = self._dialog
        label = f"{t('set.accent.custom')} {triple[0].upper()}"
        if d._custom_index >= 0:
            d._accent.setItemText(d._custom_index, label)
            d._accent.setItemData(d._custom_index, triple)
        else:
            picker = d._accent.findData(None)
            insert_at = picker if picker >= 0 else d._accent.count()
            d._accent.insertItem(insert_at, label, triple)
            d._custom_index = insert_at
        d._accent.setCurrentIndex(d._custom_index)

    def update_panel_width_enabled(self) -> None:
        """Enable the width value only when fixed-width mode is selected."""
        d = self._dialog
        d._panel_width.setEnabled(str(d._panel_width_mode.currentData()) == "fixed")

    def opacity_key(self) -> str:
        """Return the opacity slot represented by the selected panel style."""
        return "frost_opacity" if str(self._dialog._panel.currentData()) == "frost" else "opacity"

    def on_panel_style_changed(self) -> None:
        """Preserve separate opacity values while switching panel styles."""
        d = self._dialog
        d._panel_opacity[d._opacity_active_key] = d._opacity.value() / 100.0
        d._opacity_active_key = self.opacity_key()
        d._opacity.setValue(round(d._panel_opacity[d._opacity_active_key] * 100))

    def on_accent_activated(self, index: int) -> None:
        """Open the custom color picker when its combo entry is activated."""
        d = self._dialog
        if d._accent.itemData(index) is not None:
            d._accent_last_index = index
            return
        chosen = QColorDialog.getColor(QColor(d._config.accent_start), d, t("set.accent"))
        if not chosen.isValid():
            d._accent.setCurrentIndex(d._accent_last_index)
            return
        self.set_custom_accent((chosen.name(), chosen.lighter(140).name(), chosen.lighter(120).name()))
        d._accent_last_index = d._accent.currentIndex()

    def on_font_family_changed(self, font: QFont) -> None:
        """Refresh the style picker after a family selection."""
        self.rebuild_style_options(font.family())

    def emit_clear_cache(self, _checked: bool = False) -> None:
        """Forward the clear-cache action through the source-page owner."""
        self._sources.emit_clear_cache(_checked)

    def keep_one_source_checked(self, _item: QListWidgetItem | None = None) -> None:
        """Ensure the staged configuration has one enabled source."""
        self._sources.keep_one_source_checked(_item)

    def selected_sources(self) -> list[str]:
        """Return checked source identifiers in their current list order."""
        return self._sources.selected_sources()

    def chosen_font_family(self) -> str:
        """Preserve an untouched configured fallback chain when applying settings."""
        d = self._dialog
        selected = d._font_family.currentFont().family()
        return d._font_family_configured if selected == d._font_family_shown else selected

    def rebuild_style_options(self, family: str, prefer: str | None = None) -> None:
        """Repopulate styles and retain the current choice where possible."""
        font_style = self._dialog._font_style
        target = prefer if prefer is not None else font_style.currentText()
        styles = available_font_styles(family)
        font_style.blockSignals(True)
        font_style.clear()
        font_style.addItems(styles)
        index = font_style.findText(target)
        font_style.setCurrentIndex(index if index >= 0 else 0)
        font_style.blockSignals(False)

    def _form_page(self) -> tuple[QWidget, QFormLayout]:
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
        return page, form

    def _hint(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("hint")
        label.setWordWrap(True)
        return label

    def _spin(self, low: int, high: int, value: int, suffix: str) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setValue(value)
        if suffix:
            spin.setSuffix(suffix)
        return spin

    @staticmethod
    def picked_icon(icon_list: IconStrip) -> str:
        """Read the selected icon key from an icon strip."""
        item = icon_list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else DEFAULT_ICON_NAME

    @staticmethod
    def resolve_font_family(font_family: str) -> str:
        """Expose font-family resolution for the dialog compatibility boundary."""
        return resolve_font_family(font_family)

    @staticmethod
    def available_styles(family: str) -> list[str]:
        """Expose installed styles for the dialog compatibility boundary."""
        return available_font_styles(family)


__all__ = ["SettingsPageBuilder"]
