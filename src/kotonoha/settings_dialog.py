"""Tabbed settings panel.

Frameless, translucent, dark "glass" styling to match the overlay. Edits a
working copy of :class:`~kotonoha.config.Config` across grouped tabs and emits
``applied`` with the new config when the user applies/accepts. UI strings come
from :mod:`kotonoha.strings`.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import cast

from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QCloseEvent,
    QColor,
    QHideEvent,
    QIcon,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QShowEvent,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFontComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import leaf_icon, settings_theme
from .config import Config
from .platform import OverlayPlatform, OverlayPlatformFactory, QtWindowHost, SurfaceResult, WindowRectangle
from .players import PlayerInfo
from .settings_pages import SettingsPageBuilder
from .settings_widgets import IconStrip, available_font_styles, resolve_font_family
from .strings import t

_CHECKMARK_PATH = settings_theme._CHECKMARK_PATH
_PALETTES = settings_theme._PALETTES
_resolve_theme = settings_theme._resolve_theme
_skin = settings_theme._skin

# Dialog corner radius, shared by the painted background and the KWin blur region.
_RADIUS = 14

logger = logging.getLogger(__name__)


# Theme generation lives in settings_theme.py; the dialog owns only lifecycle
# and painting of the resulting window.
# The Config fields each sidebar page owns, in nav order. Used by "Reset this tab"
# to restore just the current page's fields to their defaults, leaving the rest.
_PAGE_FIELDS: tuple[tuple[str, ...], ...] = (
    ("ui_language", "theme", "frost_window", "settings_opacity"),                         # General
    ("icon_name", "window_icon_name"),                                                   # Icon
    ("font_family", "font_style", "font_size", "context_font_size", "translation_font_size"),  # Text
    ("panel_style", "panel_width_mode", "panel_width", "opacity", "frost_opacity", "panel_accent_tint"),  # Panel
    ("accent_start", "accent_end", "accent_sweep", "fx_animate", "fx_transition",
     "fx_glow", "fx_word_pop", "fx_intensity"),                                          # Effects
    ("karaoke", "lead_ms", "show_translation", "current_line_only", "lyrics_script",
     "interlude_style", "interlude_countdown"),                                          # Lyrics
    ("anchor_top", "margin_edge", "margin_x", "passthrough"),                            # Position
    (
        "lyrics_sources", "player_lock", "prefer_best_lyrics", "fuzzy_match", "cache_enabled", "cider_api_token"
    ),  # Sources
)


class SettingsDialog(QDialog):
    applied = pyqtSignal(object)  # emits Config
    clear_cache_requested = pyqtSignal()
    restart_requested = pyqtSignal()

    # Page controls are created by SettingsPageBuilder's explicit page factory.
    # Declaring them at this owner boundary keeps staged UI state typed while
    # preserving the dialog's compatibility surface for existing callers/tests.
    _ui_language: QComboBox
    _theme_combo: QComboBox
    _frost_window: QCheckBox
    _settings_opacity: QSpinBox
    _restart_btn: QPushButton
    _tray_icon_list: IconStrip
    _window_icon_list: IconStrip
    _font_family: QFontComboBox
    _font_family_shown: str
    _font_family_configured: str
    _font_style: QComboBox
    _font_size: QSpinBox
    _context_font_size: QSpinBox
    _translation_font_size: QSpinBox
    _panel: QComboBox
    _panel_width_mode: QComboBox
    _panel_width: QSpinBox
    _panel_opacity: dict[str, float]
    _opacity_active_key: str
    _opacity: QSpinBox
    _panel_tint: QCheckBox
    _accent: QComboBox
    _custom_index: int
    _accent_last_index: int
    _fx_animate: QCheckBox
    _fx_transition: QComboBox
    _fx_glow: QCheckBox
    _fx_word_pop: QCheckBox
    _fx_intensity: QComboBox
    _karaoke: QCheckBox
    _lead: QSpinBox
    _translation: QCheckBox
    _current_line_only: QCheckBox
    _lyrics_script: QComboBox
    _interlude_style: QComboBox
    _interlude_countdown: QComboBox
    _anchor: QComboBox
    _margin_edge: QSpinBox
    _margin_x: QSpinBox
    _passthrough: QCheckBox
    _player_combo: QComboBox
    _sources_list: QListWidget
    _prefer_best: QCheckBox
    _fuzzy_match: QCheckBox
    _cache_enabled: QCheckBox
    _cider_token: QLineEdit
    _clear_cache: QPushButton

    def __init__(
        self,
        config: Config,
        parent: QWidget | None = None,
        *,
        players: list[PlayerInfo] | None = None,
        platform_factory: OverlayPlatformFactory | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config.clamped()
        self._players = list(players or [])
        # Every icon strip built (tray + window), each with its own {key: item} map,
        # so accent re-renders can refresh all of them. Populated by _build_icon_picker.
        self._icon_pickers: list[tuple[IconStrip, dict[str, QListWidgetItem]]] = []
        # The UI language only takes effect on restart, so remember what is in
        # effect now to decide when to offer the restart button.
        self._initial_ui_language = config.ui_language
        self._theme = _resolve_theme(config.theme)
        self._did_fade_in = False
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Real backdrop-blur behind the whole window (frosted glass), wherever the
        # compositor advertises a blur protocol. Asking the compositor beats matching
        # on the desktop name, which claimed KDE 6.7 could blur after it dropped
        # org_kde_kwin_blur and denied Mutter, which speaks the replacement. Where
        # nothing can blur the window stays a solid panel, so it is never turned
        # see-through in front of a backdrop that will not be blurred.
        self._platform: OverlayPlatform | None = None
        if platform_factory is not None:
            self._platform = platform_factory(QtWindowHost(self))
        capabilities = self._platform.capabilities if self._platform is not None else None
        self._blur_capable = capabilities is not None and capabilities.blur
        # The cause travels with the capability, so the window can say which of the
        # four situations it is rather than repeating the requirement.
        self._blur_reason = capabilities.blur_reason if capabilities is not None else "bridge"
        # Wayland has no client-side window-opacity protocol, so animating/setting
        # windowOpacity there does nothing but spam "plugin does not support…".
        # Which session this is belongs to the platform layer: reading the Qt
        # platform name here made presentation decide a compositor fact itself, and
        # a name passed in as an argument is still that same decision.
        self._window_opacity_ok = capabilities is None or capabilities.window_opacity
        self._frosted = self._blur_capable and config.frost_window
        # See-through level for the window surfaces. NOT setWindowOpacity — the Qt
        # Wayland plugin ignores that (no client-side opacity protocol); instead the
        # painted window fill + card alpha carry it, so it works under KWin.
        self._win_opacity = config.settings_opacity
        self.setStyleSheet(_skin(config.accent_start, self._theme, self._frosted, self._win_opacity))

        # Sidebar categories drive a stacked content area (replaces top tabs).
        self._stack = QStackedWidget()
        self._nav = QListWidget()
        self._nav.setObjectName("nav")
        self._nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # The page builder owns controls and page-local handlers; this dialog owns
        # their lifetime and the staged configuration they edit.
        self._page_builder = SettingsPageBuilder(self)
        self._page_builders = (
            self._page_builder.general_page,
            self._page_builder.icon_page,
            self._page_builder.text_page,
            self._page_builder.panel_page,
            self._page_builder.effects_page,
            self._page_builder.lyrics_page,
            self._page_builder.position_page,
            self._page_builder.sources_page,
        )
        for key, builder in zip(
            ("tab.general", "tab.icon", "tab.text", "tab.panel", "tab.effects",
             "tab.lyrics", "tab.position", "tab.sources"),
            self._page_builders,
            strict=True,
        ):
            self._nav.addItem(QListWidgetItem(t(key)))
            self._stack.addWidget(builder())
        self._nav.setCurrentRow(0)
        self._stack.setCurrentIndex(0)
        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self.setMinimumWidth(560)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        for std, key in (
            (QDialogButtonBox.StandardButton.Ok, "btn.ok"),
            (QDialogButtonBox.StandardButton.Cancel, "btn.cancel"),
            (QDialogButtonBox.StandardButton.Apply, "btn.apply"),
            (QDialogButtonBox.StandardButton.RestoreDefaults, "btn.reset_tab"),
        ):
            btn = buttons.button(std)
            if btn is not None:
                btn.setText(t(key))
                btn.setIcon(QIcon())  # drop the platform ✓/✕ glyphs; text-only, theme-safe
        apply_button = buttons.button(QDialogButtonBox.StandardButton.Apply)
        if apply_button is not None:
            apply_button.clicked.connect(self._emit)
        reset_button = buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        if reset_button is not None:
            # ResetRole sits on the left of the box, away from OK/Apply — a reset is
            # per-tab (just this page's fields), not the whole config.
            reset_button.clicked.connect(self._reset_current_page)

        # The content sits in a raised "card" surface while the sidebar stays on the
        # base dialog colour, so the two read as distinct layers (depth) without a
        # hard divider line between them.
        card = QWidget()
        card.setObjectName("contentCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.addWidget(self._stack)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        body.addWidget(self._nav)
        body.addWidget(card, 1)

        header_line = QWidget()
        header_line.setObjectName("navDivider")
        header_line.setFixedHeight(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        layout.addLayout(self._title_bar())
        layout.addWidget(header_line)
        layout.addLayout(body, 1)
        layout.addWidget(buttons)

    # --- chrome ---

    def _title_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(9)
        self._logo_badge = QLabel()
        self._update_logo_badge()  # accent-tinted leaf logo (falls back to the app icon)
        bar.addWidget(self._logo_badge)
        title = QLabel(t("settings.title"))
        title.setObjectName("dialogTitle")  # styled by the theme QSS
        close_btn = QPushButton("✕")
        close_btn.setObjectName("closeButton")
        close_btn.setFixedSize(26, 26)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.reject)
        bar.addWidget(title)
        bar.addStretch(1)
        bar.addWidget(close_btn)
        return bar

    def paintEvent(self, a0: QPaintEvent | None) -> None:  # noqa: ARG002
        palette = _PALETTES[self._theme]
        rgba = cast("dict[str, tuple[int, int, int, int]]", palette)
        bg = rgba["window_bg"]
        if self._frosted:
            # Translucent so the KWin blur behind the window shows through as frost.
            bg = (bg[0], bg[1], bg[2], 165)
        else:
            # Opacity drives the window fill directly: 100% is fully opaque (alpha
            # 255, not the palette's slightly-translucent default), 0% invisible.
            bg = (bg[0], bg[1], bg[2], max(0, min(255, round(255 * self._win_opacity))))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(*bg))
        painter.setPen(QPen(QColor(*rgba["window_border"])))
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.drawRoundedRect(rect, float(_RADIUS), float(_RADIUS))

    def _apply_blur(self) -> None:
        if not self._frosted or self._platform is None:
            return
        blur = self._platform.blur
        if blur is None:
            return
        result = blur.set_blur_region(WindowRectangle(0, 0, self.width(), self.height()), _RADIUS)
        if result.succeeded:
            return
        # The window is painted translucent because a compositor blur is meant to sit
        # behind it. Discarding this left the panel see-through over an unblurred
        # backdrop — unreadable — while still reporting frosted glass as on.
        logger.warning("Frosted glass unavailable, falling back to a solid panel: %s", result.reason)
        self._frosted = False
        self.setStyleSheet(_skin(self._config.accent_start, self._theme, self._frosted, self._win_opacity))
        self.update()

    def hideEvent(self, a0: QHideEvent | None) -> None:
        if self._frosted and self._platform is not None:
            blur = self._platform.blur
            if blur is not None:
                blur.set_blur_region(None)
        super().hideEvent(a0)

    def done(self, a0: int) -> None:
        """Close the owned surface before the dialog becomes reusable or hidden."""
        result = self._close_platform()
        if not result.succeeded:
            logger.warning("Settings surface shutdown was incomplete: %s", result.reason)
            return
        super().done(a0)

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        """Release the platform surface when the dialog is explicitly closed."""
        result = self._close_platform()
        if not result.succeeded:
            logger.warning("Settings surface shutdown was incomplete: %s", result.reason)
            if a0 is not None:
                a0.ignore()
            return
        super().closeEvent(a0)

    def _close_platform(self) -> SurfaceResult:
        """Release the optional platform surface and report whether it completed."""
        if self._platform is None:
            return SurfaceResult.applied()
        return self._platform.surface.close()

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)
        self._apply_blur()  # keep the blur region matched to the window size

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        # Wayland forbids client-side move(); use the compositor's system move.
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            if handle is not None and handle.startSystemMove():
                a0.accept()
                return
        super().mousePressEvent(a0)

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        if self._platform is not None:
            prepared = self._platform.surface.prepare()
            if not prepared.succeeded:
                logger.warning("Settings surface preparation failed: %s", prepared.reason)
            else:
                activated = self._platform.surface.activate()
                if not activated.succeeded:
                    logger.warning("Settings surface activation failed: %s", activated.reason)
        # Now the stylesheet metrics are active: size the sidebar to its widest
        # label (in any language) and the content to the tallest page, so switching
        # sections never resizes the window and the nav never truncates.
        self._nav.setFixedWidth(self._nav.sizeHintForColumn(0) + 30)
        self._stack.setMinimumWidth(400)
        widgets = (self._stack.widget(i) for i in range(self._stack.count()))
        tallest = max((widget.sizeHint().height() for widget in widgets if widget is not None), default=0)
        self._stack.setMinimumHeight(tallest)
        needed = self._nav.width() + 1 + 400 + 46  # nav + divider + content + margins/spacing
        if self.minimumWidth() < needed:
            self.setMinimumWidth(needed)
        if self.width() < needed:
            self.resize(needed, self.height())
        # Gentle fade-in on first show (once), if animations are enabled. Skipped on
        # Wayland, where windowOpacity is a no-op that only logs a warning per frame.
        if self._config.fx_animate and not self._did_fade_in and self._window_opacity_ok:
            self._did_fade_in = True
            anim = QPropertyAnimation(self, b"windowOpacity", self)
            anim.setDuration(160)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        self._apply_blur()  # frost the window backdrop once it is shown + sized

    # --- page compatibility and chrome helpers ---

    def _update_logo_badge(self) -> None:
        """Set the title-bar badge to the accent-tinted leaf logo."""
        pixmap = leaf_icon.render_leaf(leaf_icon.ACCENT, self._config.accent_start, size=44)
        pixmap.setDevicePixelRatio(2.0)
        self._logo_badge.setPixmap(pixmap)

    def _update_restart_hint(self) -> None:
        """Show restart when the staged UI language differs from the active one."""
        self._restart_btn.setVisible(self._ui_language.currentData() != self._initial_ui_language)

    def _request_restart(self) -> None:
        """Persist staged settings before asking the application to restart."""
        self._emit()
        self.restart_requested.emit()

    @staticmethod
    def _resolve_font_family(font_family: str) -> str:
        """Resolve the configured fallback chain for the font picker."""
        return resolve_font_family(font_family)

    def _set_custom_accent(self, triple: tuple[str, str, str]) -> None:
        """Delegate custom-accent selection to the page builder."""
        self._page_builder.set_custom_accent(triple)

    def _available_styles(self, family: str) -> list[str]:
        """Return the installed styles for a font family."""
        return available_font_styles(family)

    @staticmethod
    def _picked_icon(icon_list: IconStrip) -> str:
        """Read an icon key through the page-builder boundary."""
        return SettingsPageBuilder.picked_icon(icon_list)

    def _selected_sources(self) -> list[str]:
        """Read checked lyric sources through the page-builder boundary."""
        return self._page_builder.selected_sources()

    def _chosen_font_family(self) -> str:
        """Return the selected family while preserving an untouched fallback chain."""
        return self._page_builder.chosen_font_family()

    def _refresh_generated_icons(self) -> None:
        """Refresh accent-dependent icon previews."""
        self._page_builder.refresh_generated_icons()
    def current_config(self) -> Config:
        accent_data = self._accent.currentData()
        if accent_data is None:  # the picker entry left selected — keep the current accent
            accent_data = (self._config.accent_start, self._config.accent_end, self._config.accent_sweep)
        accent_start, accent_end, accent_sweep = accent_data
        self._panel_opacity[self._opacity_active_key] = self._opacity.value() / 100.0  # save the active slider
        return replace(
            self._config,
            ui_language=str(self._ui_language.currentData()),
            theme=str(self._theme_combo.currentData()),
            frost_window=self._frost_window.isChecked(),
            settings_opacity=self._settings_opacity.value() / 100.0,
            lyrics_script=str(self._lyrics_script.currentData()),
            interlude_style=str(self._interlude_style.currentData()),
            interlude_countdown=str(self._interlude_countdown.currentData()),
            icon_name=self._picked_icon(self._tray_icon_list),
            window_icon_name=self._picked_icon(self._window_icon_list),
            font_family=self._chosen_font_family(),
            font_style=self._font_style.currentText(),
            font_size=self._font_size.value(),
            context_font_size=self._context_font_size.value(),
            translation_font_size=self._translation_font_size.value(),
            opacity=self._panel_opacity["opacity"],
            frost_opacity=self._panel_opacity["frost_opacity"],
            panel_style=str(self._panel.currentData()),
            panel_width_mode=str(self._panel_width_mode.currentData()),
            panel_width=self._panel_width.value(),
            panel_accent_tint=self._panel_tint.isChecked(),
            accent_start=accent_start,
            accent_end=accent_end,
            accent_sweep=accent_sweep,
            fx_animate=self._fx_animate.isChecked(),
            fx_transition=str(self._fx_transition.currentData()),
            fx_glow=self._fx_glow.isChecked(),
            fx_word_pop=self._fx_word_pop.isChecked(),
            fx_intensity=str(self._fx_intensity.currentData()),
            karaoke=self._karaoke.isChecked(),
            lead_ms=self._lead.value(),
            show_translation=self._translation.isChecked(),
            current_line_only=self._current_line_only.isChecked(),
            anchor_top=bool(self._anchor.currentData()),
            margin_edge=self._margin_edge.value(),
            margin_x=self._margin_x.value(),
            screen_name=self._config.screen_name,
            passthrough=self._passthrough.isChecked(),
            lyrics_sources=self._selected_sources(),
            prefer_best_lyrics=self._prefer_best.isChecked(),
            fuzzy_match=self._fuzzy_match.isChecked(),
            cache_enabled=self._cache_enabled.isChecked(),
            cider_api_token=self._cider_token.text().strip(),
            player_lock=str(self._player_combo.currentData()),
        ).clamped()

    def _reset_current_page(self) -> None:
        """Restore only the current page's fields to their defaults, keeping every
        other page's edits, then rebuild that page from the reset config. The change
        is staged like any other edit — the user still applies or cancels it."""
        idx = self._nav.currentRow()
        if not 0 <= idx < len(self._page_builders):
            return
        defaults = Config()
        self._config = self._reset_page_values(self.current_config(), defaults, idx)
        # Drop the icon strips the page being rebuilt had registered, so _icon_tab
        # re-adding them doesn't leave stale duplicates. (Compare the underlying
        # page index explicitly: bound-method reflection would hide ownership.
        if idx == 1:
            self._icon_pickers.clear()
        new_page = self._page_builders[idx]()
        old_page = self._stack.widget(idx)
        self._stack.insertWidget(idx, new_page)
        if old_page is not None:
            self._stack.removeWidget(old_page)
            old_page.deleteLater()
        self._stack.setCurrentIndex(idx)

    @staticmethod
    def _reset_page_values(current: Config, defaults: Config, index: int) -> Config:
        """Reset one page through explicit fields while preserving other edits."""
        if index == 0:
            return replace(
                current,
                ui_language=defaults.ui_language,
                theme=defaults.theme,
                frost_window=defaults.frost_window,
                settings_opacity=defaults.settings_opacity,
            ).clamped()
        if index == 1:
            return replace(current, icon_name=defaults.icon_name, window_icon_name=defaults.window_icon_name).clamped()
        if index == 2:
            return replace(
                current,
                font_family=defaults.font_family,
                font_style=defaults.font_style,
                font_size=defaults.font_size,
                context_font_size=defaults.context_font_size,
                translation_font_size=defaults.translation_font_size,
            ).clamped()
        if index == 3:
            return replace(
                current,
                panel_style=defaults.panel_style,
                panel_width_mode=defaults.panel_width_mode,
                panel_width=defaults.panel_width,
                opacity=defaults.opacity,
                frost_opacity=defaults.frost_opacity,
                panel_accent_tint=defaults.panel_accent_tint,
            ).clamped()
        if index == 4:
            return replace(
                current,
                accent_start=defaults.accent_start,
                accent_end=defaults.accent_end,
                accent_sweep=defaults.accent_sweep,
                fx_animate=defaults.fx_animate,
                fx_transition=defaults.fx_transition,
                fx_glow=defaults.fx_glow,
                fx_word_pop=defaults.fx_word_pop,
                fx_intensity=defaults.fx_intensity,
            ).clamped()
        if index == 5:
            return replace(
                current,
                karaoke=defaults.karaoke,
                lead_ms=defaults.lead_ms,
                show_translation=defaults.show_translation,
                current_line_only=defaults.current_line_only,
                lyrics_script=defaults.lyrics_script,
                interlude_style=defaults.interlude_style,
                interlude_countdown=defaults.interlude_countdown,
            ).clamped()
        if index == 6:
            return replace(
                current,
                anchor_top=defaults.anchor_top,
                margin_edge=defaults.margin_edge,
                margin_x=defaults.margin_x,
                passthrough=defaults.passthrough,
            ).clamped()
        if index == 7:
            return replace(
                current,
                lyrics_sources=defaults.lyrics_sources,
                player_lock=defaults.player_lock,
                prefer_best_lyrics=defaults.prefer_best_lyrics,
                fuzzy_match=defaults.fuzzy_match,
                cache_enabled=defaults.cache_enabled,
                cider_api_token=defaults.cider_api_token,
            ).clamped()
        raise ValueError(f"unknown settings page index: {index}")

    def _emit(self) -> None:
        self._config = self.current_config()
        # Toggle the frosted backdrop live: apply/clear the KWin blur to match the
        # new setting, so the re-skin below can pick the right (translucent) card.
        frosted = self._blur_capable and self._config.frost_window
        if frosted != self._frosted and self._platform is not None:
            self._frosted = frosted
            blur = self._platform.blur
            if blur is not None:
                if frosted:
                    self._apply_blur()
                else:
                    blur.set_blur_region(None)
        # Re-skin the dialog itself so an accent OR theme change is visible right
        # away (tab underline, checkbox fill, light/dark palette) rather than only
        # after Settings is closed and reopened.
        self._theme = _resolve_theme(self._config.theme)
        self._win_opacity = self._config.settings_opacity  # commit the see-through level
        self.setStyleSheet(_skin(self._config.accent_start, self._theme, self._frosted, self._win_opacity))
        self._update_logo_badge()  # re-tint the leaf logo to the new accent
        self._refresh_generated_icons()  # re-tint the accent/tile icon previews
        self.update()  # repaint the frameless background (theme / frost)
        self.applied.emit(self._config)

    def _accept(self) -> None:
        self._emit()
        self.accept()
