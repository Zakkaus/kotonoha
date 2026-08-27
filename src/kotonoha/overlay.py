"""The lyrics overlay window.

A frameless, translucent, top-most window that floats above fullscreen apps via
the Wayland layer-shell bridge (with graceful fallback). It shows the previous
line, the current line with a karaoke sweep, an optional translation, and the
next line. The application display coordinator supplies the current media time;
the widget only applies presentation settings and paints it.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QShowEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsDropShadowEffect,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .config import TRACK_OFFSET_STEP_MS, Config, set_track_offset, track_identity_key
from .display.layout import FontFitPolicy
from .display.models import EMPTY_FRAME, DisplayFrame, DisplayState
from .karaoke_label import KaraokeLabel
from .lyrics.models import LyricLine
from .overlay_chrome import OverlayChromeController
from .overlay_style import OverlayAppearance
from .overlay_surface import OverlaySurfaceController, ScreenLike
from .platform import DefaultOverlayPlatformFactory, QtWindowHost
from .platform.overlay_contracts import DragMode, LayerShellBridge, Output, OverlayPlatform
from .state import LyricsState
from .strings import t

logger = logging.getLogger(__name__)

#: The marker stands in for a lyric, so it is drawn under the lyric size — but it
#: still has to read as part of the same panel, which at 0.42 it did not: it sat
#: small and crowded against the lines above and below.
INTERLUDE_SCALE = 0.62
PILL_RADIUS = 16  # corner radius shared by the pill paint and the input region
_FONT_FIT_POLICY = FontFitPolicy()


class LyricsOverlay(QWidget):
    # Emitted when the on-HUD lock button is clicked (controller flips passthrough).
    passthrough_toggle_requested = pyqtSignal()
    # Emitted when the on-HUD gear button is clicked.
    settings_requested = pyqtSignal()
    # Emitted after a drag, with the edge margin, horizontal offset relative to
    # the target output's center, and output name. The offset is output-local;
    # virtual-desktop origins are deliberately excluded.
    position_changed = pyqtSignal(int, int, str)
    track_offset_changed = pyqtSignal(str, int)

    _container: QWidget
    _control_bar: QWidget
    _lock_btn: QToolButton
    _earlier_btn: QToolButton
    _later_btn: QToolButton
    _settings_btn: QToolButton
    _chrome: OverlayChromeController

    def __init__(self, state: LyricsState, config: Config, controller: LayerShellBridge | None = None) -> None:
        super().__init__()
        self._state = state
        self._config = config
        self._frame = EMPTY_FRAME
        self._passthrough = config.passthrough
        self._track_key = ""
        self._appearance = OverlayAppearance()
        # Cache only the rendered marker text; interlude timing itself belongs to
        # DisplayFrame and is never inferred by this widget.
        self._interlude_active = False
        self._chrome = OverlayChromeController(self)
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self._restore_after_offset_feedback)
        app = QApplication.instance()
        platform_factory: DefaultOverlayPlatformFactory
        if controller is None:
            platform_factory = DefaultOverlayPlatformFactory()
            bridge = platform_factory.controller
        else:
            bridge = controller
            platform_factory = DefaultOverlayPlatformFactory(bridge)
        self._surface = OverlaySurfaceController(
            self,
            config,
            controller=bridge,
            platform_factory=platform_factory,
            band_height=self._band_height,
            container_geometry=self._container_geometry,
        )
        self.setWindowTitle("Kotonoha")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._build_ui()
        self.apply_config(config)

        self._state.frame_changed.connect(self._on_frame)
        if isinstance(app, QGuiApplication):
            app.screenAdded.connect(self._on_screen_added)
            app.screenRemoved.connect(self._on_screen_removed)
        self._surface.set_output_handler(self._restore_output)

        self._on_frame(self._state.frame)

    @property
    def _controller(self) -> LayerShellBridge:
        """Expose the surface bridge for the explicit test/platform boundary."""
        return self._surface.controller

    @property
    def _host(self) -> QtWindowHost:
        """Expose the toolkit host for platform adapter tests."""
        return self._surface.host

    @property
    def _platform(self) -> OverlayPlatform:
        """Expose the selected platform adapter for the compatibility boundary."""
        return self._surface.platform

    @_platform.setter
    def _platform(self, value: OverlayPlatform) -> None:
        self._surface.platform = value

    @property
    def _layer_pos(self) -> QPoint:
        """Expose the surface-local position to existing placement tests."""
        return self._surface.layer_pos

    @_layer_pos.setter
    def _layer_pos(self, value: QPoint) -> None:
        self._surface.layer_pos = value

    @property
    def _active_screen(self) -> ScreenLike | None:
        """Expose the active output to existing placement tests."""
        return self._surface.active_screen

    @_active_screen.setter
    def _active_screen(self, value: ScreenLike | None) -> None:
        self._surface.active_screen = value

    @property
    def _dragging(self) -> bool:
        """Expose drag state owned by the platform surface."""
        return self._surface.dragging

    @_dragging.setter
    def _dragging(self, value: bool) -> None:
        self._surface.dragging = value

    @property
    def _drag_moved(self) -> bool:
        """Expose drag state owned by the platform surface."""
        return self._surface.drag_moved

    @_drag_moved.setter
    def _drag_moved(self, value: bool) -> None:
        self._surface.drag_moved = value

    @property
    def _drag_applied(self) -> bool:
        """Expose drag state owned by the platform surface."""
        return self._surface.drag_applied

    @_drag_applied.setter
    def _drag_applied(self, value: bool) -> None:
        self._surface.drag_applied = value

    @property
    def _drag_local(self) -> QPoint:
        """Expose the last local pointer coordinate to placement tests."""
        return self._surface.drag_local

    @_drag_local.setter
    def _drag_local(self, value: QPoint) -> None:
        self._surface.drag_local = value

    def _container_geometry(self):
        """Return the current pill geometry for the platform surface boundary."""
        return self._container.geometry()

    # --- UI ---

    def _build_ui(self) -> None:
        self._container = QWidget(self)
        self._container.installEventFilter(self)  # track its size for the input region
        layout = QVBoxLayout(self._container)
        layout.setContentsMargins(22, 10, 22, 14)
        layout.setSpacing(4)

        layout.addWidget(self._build_control_bar())

        self._prev_label = self._make_context_label()
        self._current = KaraokeLabel(self._container)
        # Translation is a KaraokeLabel too: no per-word timing -> it sweeps the
        # whole line following the current line's progress (the user's choice).
        self._translation = KaraokeLabel(self._container)
        self._next_label = self._make_context_label()

        for w in (self._prev_label, self._current, self._translation, self._next_label):
            layout.addWidget(w, alignment=Qt.AlignmentFlag.AlignHCenter)
        # Cheap readability shadows on the context labels (they repaint only on
        # snapshot changes, so a blur effect here costs nothing per frame; the
        # karaoke labels draw their own offset shadow instead).
        for label in (self._prev_label, self._next_label):
            label.setGraphicsEffect(self._make_text_shadow())

        # Fixed-size, draggable window (positioned via layer-shell margins); the
        # content container hugs its text and sits centered inside it.
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)
        self._root.addStretch(1)
        self._root.addWidget(self._container, 0, Qt.AlignmentFlag.AlignHCenter)
        self._root.addStretch(1)

    def _make_text_shadow(self) -> QGraphicsDropShadowEffect:
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(8)
        shadow.setOffset(0, 1)
        shadow.setColor(QColor(0, 0, 0, 200))
        return shadow

    def _build_control_bar(self) -> QWidget:
        """Build the overlay's interactive chrome through its owner."""
        return self._chrome.build()

    def _update_lock_icon(self) -> None:
        self._chrome.update_icons()

    def _update_chrome(self) -> None:
        """Locking only hides the interactive controls (you can't click them once
        the surface is click-through). The panel background is governed by the
        panel-style setting, NOT the lock state — see paintEvent."""
        self._chrome.update_visibility()

    def _make_context_label(self) -> QLabel:
        label = QLabel("")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        return label

    def _set_context_text(self, label: QLabel, text: str) -> None:
        """Set a prev/next context line, eliding a too-long line with an ellipsis so
        it never overflows the panel (matters most in fixed-width mode)."""
        width = label.maximumWidth()
        if text and 0 < width < 16_777_215:
            text = label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, width)
        label.setText(text)

    # --- config ---

    def apply_config(self, config: Config) -> None:
        self._config = config
        self._surface.update_config(config)
        self._surface.set_input_mode(config.passthrough)
        self._passthrough = config.passthrough
        self._set_active_screen(self._configured_screen() or self._active_screen or self.screen())
        self._update_lock_icon()
        # Configure the pill width for the fit/fixed mode; `avail` is the inner width
        # the lyric labels may use before a long line scrolls (main) or elides (rest).
        avail = self._configure_panel_width()
        families = self._font_families()
        base, shadow, context_css = self._text_colors()

        current_font = QFont()
        current_font.setFamilies(families)
        current_font.setPixelSize(config.font_size)
        if config.font_style:
            current_font.setStyleName(config.font_style)  # e.g. "Bold", "Light Italic"
        self._current.set_style(
            current_font, config.accent_start, config.accent_end, config.accent_sweep, base, shadow
        )
        self._current.set_effects(
            glow=config.fx_glow, word_pop=config.fx_word_pop,
            intensity=config.fx_intensity, animate=config.fx_animate,
            transition=config.fx_transition,
        )
        self._current.set_max_width(avail)

        family_stack = ", ".join(f"'{name}'" for name in families)
        for label in (self._prev_label, self._next_label):
            label.setStyleSheet(
                f"color: {context_css}; font-size: {config.context_font_size}px; "
                f"font-family: {family_stack};"
            )
            label.setMaximumWidth(avail)
            # Keep the context halo consistent with the main line: a light halo on
            # the white panel (dark text), a dark halo elsewhere — otherwise the
            # black shadow smudges dark-on-white and vanishes at low white opacity.
            effect = label.graphicsEffect()
            if isinstance(effect, QGraphicsDropShadowEffect):
                effect.setColor(shadow)

        trans_font = QFont()
        trans_font.setFamilies(families)
        trans_font.setPixelSize(config.translation_font_size)
        trans_font.setItalic(True)
        self._translation.set_style(
            trans_font, config.accent_start, config.accent_end, config.accent_sweep, base, shadow
        )
        # Secondary line: no glow/pop, but honour the animation toggle + style.
        self._translation.set_effects(
            glow=False, word_pop=False, intensity=config.fx_intensity,
            animate=config.fx_animate, transition=config.fx_transition,
        )
        self._translation.set_max_width(avail)
        self._translation.setVisible(config.show_translation)
        self._update_context_visibility()

        # Opacity is the panel's own fill translucency (see paintEvent / _panel_alpha),
        # so the window itself stays fully opaque — the lyric text is always crisp and
        # lowering opacity (even to 0) only fades the panel, never the text. (We do NOT
        # call setWindowOpacity: the Qt Wayland plugin ignores it and just warns.)
        self._update_chrome()
        self._apply_window_geometry()
        self.update()
        QTimer.singleShot(0, self._apply_blur)  # panel_style may have changed

    # --- geometry (fixed-size, margin-positioned panel) ---

    def _font_families(self) -> list[str]:
        """Return the configured family and the appearance fallback chain."""
        return self._appearance.font_families(self._config)

    def _configure_panel_width(self) -> int:
        """Set the pill container's width for the current mode and return the inner
        width available to the lyric text. Fixed mode pins the pill so it does not
        resize with the line length; fit mode lets it hug the text as before."""
        window_w = self._window_size()[0]
        if self._config.panel_width_mode == "fixed":
            pill_w = max(240, min(self._config.panel_width, window_w - 8))
            self._container.setFixedWidth(pill_w)
            return max(120, pill_w - 44)  # minus the container's 22+22 h-margins
        # Fit-to-text: release any pinned width so the pill hugs its content again.
        self._container.setMinimumWidth(0)
        self._container.setMaximumWidth(16_777_215)
        return _FONT_FIT_POLICY.content_width(window_w)

    def _band_height(self) -> int:
        main = self._config.font_size
        context = 0 if self._config.current_line_only else self._config.context_font_size
        translation = self._config.translation_font_size if self._config.show_translation else 0
        lines = int(main * 1.6) + 2 * int(context * 1.4) + int(translation * 1.6)
        chrome = 22 + 24 + 34  # control bar + container v-margins + spacing/slack
        return max(140, lines + chrome)

    def _update_context_visibility(self) -> None:
        visible = not self._config.current_line_only
        self._prev_label.setVisible(visible)
        self._next_label.setVisible(visible)

    def _configured_screen(self) -> ScreenLike | None:
        """Return the configured screen through the platform surface owner."""
        return self._surface.configured_screen(QGuiApplication.screens())

    def _set_active_screen(self, screen: ScreenLike | None) -> None:
        """Update the surface's active output binding."""
        self._surface.set_active_screen(screen)

    def _target_screen(self) -> ScreenLike | None:
        """Select a usable output for view geometry and platform operations."""
        screens = QGuiApplication.screens()
        return self._surface.target_screen(
            screens,
            configured=self._configured_screen(),
            widget_screen=self.screen(),
            primary=QApplication.primaryScreen(),
        )

    @staticmethod
    def _usable_screen(screen: ScreenLike | None) -> ScreenLike | None:
        """Return a usable screen through the platform surface boundary."""
        return OverlaySurfaceController.usable_screen(screen)

    @staticmethod
    def _output(screen: ScreenLike | None) -> Output | None:
        """Convert a screen into the platform output contract."""
        return OverlaySurfaceController.output(screen)

    def _connected_outputs(self) -> tuple[Output, ...]:
        """Return currently connected usable outputs."""
        return self._surface.connected_outputs(QGuiApplication.screens())

    def _on_screen_removed(self, screen: ScreenLike) -> None:
        """Forward screen removal to the surface lifecycle owner."""
        self._surface.screen_removed(screen, QGuiApplication.screens())

    def _on_screen_added(self, screen: ScreenLike) -> None:
        """Forward screen addition to the surface lifecycle owner."""
        del screen
        self._surface.screen_added(QGuiApplication.screens())

    def _restore_output(self, output: Output) -> bool:
        """Rebuild a returning output through the surface lifecycle owner."""
        return self._surface.restore_output(
            output,
            QGuiApplication.screens(),
            activate=self.activate_layer_shell,
            show=self.show,
        )

    @staticmethod
    def _same_screen(first: ScreenLike | None, second: ScreenLike | None) -> bool:
        """Compare output identity and geometry."""
        return OverlaySurfaceController.same_screen(first, second)

    @staticmethod
    def _screen_for_global_point(
        point: QPoint,
        screens: list[ScreenLike],
        fallback: ScreenLike | None,
    ) -> ScreenLike | None:
        """Find the screen under a global point."""
        return OverlaySurfaceController.screen_for_global_point(point, screens, fallback)

    def _window_size(self) -> tuple[int, int]:
        """Return the stable surface size for the active output."""
        return self._surface.window_size(self._target_screen())

    def _compute_layer_pos(self, width: int, height: int) -> QPoint:
        """Compute the configured screen-local surface position."""
        return self._surface.compute_layer_pos(width, height, self._target_screen())

    def _apply_window_geometry(self, *, reset_position: bool = True) -> None:
        """Delegate sizing and placement to the platform surface owner."""
        self._surface.apply_window_geometry(QGuiApplication.screens(), reset_position=reset_position)

    def _bind_widget_screen(self, screen: ScreenLike | None) -> None:
        """Bind the Qt widget to the selected screen when it is a real QScreen."""
        self._surface.bind_widget_screen(screen)

    # --- frame handling ---

    def _on_frame(self, frame: DisplayFrame) -> None:
        self._frame = frame
        has_lyrics = frame.state is DisplayState.LYRICS_AVAILABLE and frame.document is not None
        if has_lyrics and frame.current is None and frame.interlude_line is not None:
            self._show_interlude(frame)
            self._refresh_input_region()
            return

        if self._interlude_active:
            self._interlude_active = False
            self._current.set_scale(1.0)
        if not has_lyrics or frame.current is None:
            self._show_empty(frame)
            self._refresh_input_region()
            return

        self._container.setVisible(True)
        document = frame.document
        self._set_track_key_from_frame(frame)
        current = frame.current
        if current is None:
            self._show_empty(frame)
            self._refresh_input_region()
            return
        previous = frame.previous
        next_line = frame.next
        self._set_context_text(self._prev_label, previous.text if previous else "")
        self._set_context_text(self._next_label, next_line.text if next_line else "")
        word_mode = document is not None and document.has_word_timing and current.has_word_timing
        self._current.set_line(current, word_mode and self._config.karaoke)

        if self._config.show_translation and frame.translation is not None:
            self._translation.set_line(frame.translation, False)
            self._translation.setVisible(True)
        else:
            self._translation.set_line(None, False)
            self._translation.setVisible(False)
        self._current.set_progress(frame.line_progress, frame.word_progress)
        self._translation.set_progress(frame.line_progress, None)
        self._refresh_input_region()

    def _refresh_media_time(self) -> None:
        """Reapply the frame-owned progress after a display setting changes."""
        self._current.set_progress(self._frame.line_progress, self._frame.word_progress)
        self._translation.set_progress(self._frame.line_progress, None)

    def _set_track_key(self, title: str, artist: str, duration: float | None) -> None:
        """Set the presentation offset key for the frame currently being drawn."""
        self._track_key = track_identity_key(title, artist, duration)

    def _set_track_key_from_frame(self, frame: DisplayFrame) -> None:
        """Derive the presentation offset key from a normalized display frame."""
        track = frame.track
        document = frame.document
        title_value = track.title if track is not None else document.title if document is not None else None
        artist_value = track.artist if track is not None else document.artist if document is not None else None
        duration = track.duration_s if track is not None else document.duration_s if document is not None else None
        title = title_value if title_value is not None else ""
        artist = artist_value if artist_value is not None else ""
        self._set_track_key(title, artist, duration)

    def _show_interlude(self, frame: DisplayFrame) -> None:
        """Stand in for the line while an intro or a break is playing.

        The surrounding lines stay put: the panel is mid-song, and collapsing it to
        the idle state would read as though playback had stopped.
        """
        # A marker stands in for the words; drawn at the lyric size it dwarfs them.
        self._current.set_scale(INTERLUDE_SCALE)
        self._container.setVisible(True)
        self._set_track_key_from_frame(frame)
        previous = frame.previous
        next_line = frame.next
        self._set_context_text(self._prev_label, previous.text if previous else "")
        self._set_context_text(self._next_label, next_line.text if next_line else "")
        self._translation.set_line(None, False)
        self._translation.setVisible(False)
        interlude_line = frame.interlude_line
        if interlude_line is None:
            return
        self._interlude_active = True
        self._current.set_line(interlude_line, False)
        self._current.set_progress(frame.line_progress, None)

    def _show_empty(self, frame: DisplayFrame) -> None:
        self._track_key = ""
        self._prev_label.setText("")
        self._next_label.setText("")
        # No translation line while idle; the title carries the whole message.
        self._translation.set_line(None, False)
        self._translation.setVisible(False)
        self._current.set_progress(None, None)
        title_line = frame.fallback
        if title_line is None:
            # Nothing playing: a default line so the panel isn't a blank box.
            title_line = LyricLine(
                index=0, id="title", start=0.0, end=1e9,
                text=t("overlay.idle"), translation="", words=(),
            )
        self._current.set_line(title_line, False)
        self._current.set_media_time(None)

    # --- layer shell / placement ---

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        # A rebuild has already computed the position; recomputing it here would
        # throw away the output the surface was just put back on.
        self._apply_window_geometry(reset_position=not self._surface.consume_preserve_position())
        QTimer.singleShot(0, self.activate_layer_shell)
        QTimer.singleShot(100, self.activate_layer_shell)

    def activate_layer_shell(self) -> bool:
        """Promote to a layer surface. MUST be called before the first show().

        Returns whether the surface is now a layer surface, so a caller that is
        rebuilding one can tell a real rebuild from a fallback."""
        return self._surface.activate(QGuiApplication.screens(), fallback=self._fallback_position)

    def _fallback_position(self, screen: ScreenLike | None = None) -> None:
        """Position as an ordinary window, for X11 and for a failed activation.

        Through the host rather than the platform: this runs when Layer Shell is
        unavailable *or* when it is available and activation failed, and in the
        second case the Layer Shell adapter is still in place — asking it to move
        would set a native anchor on a surface that was never promoted, which is
        not a fallback at all.
        """
        self._surface.fallback_position(screen if screen is not None else self._target_screen())

    def set_passthrough(self, enabled: bool) -> None:
        self._passthrough = enabled
        self._surface.set_input_mode(enabled)
        self._update_lock_icon()
        self._update_chrome()
        # Chrome visibility just changed the pill size; lay out, then set the region.
        QTimer.singleShot(0, self._apply_input_region)

    def _apply_input_region(self) -> None:
        """Locked -> full click-through. Unlocked -> only the visible pill catches
        clicks, so the big transparent band around it stays click-through."""
        self._surface.set_input_mode(self._passthrough)

    def _refresh_input_region(self) -> None:
        if not self._passthrough:
            QTimer.singleShot(0, self._apply_input_region)

    def _nudge_earlier(self) -> None:
        """Move this track's lyrics earlier by one step.

        A bound method per direction rather than a lambda closing over the step:
        PyQt holds a bound method's receiver weakly, so the connection dies with the
        widget instead of firing into a deleted C++ object.
        """
        self._nudge_offset(TRACK_OFFSET_STEP_MS)

    def _nudge_later(self) -> None:
        """Move this track's lyrics later by one step."""
        self._nudge_offset(-TRACK_OFFSET_STEP_MS)

    def _nudge_offset(self, delta_ms: int) -> None:
        if not self._track_key:
            return
        current = self._config.track_offsets.get(self._track_key, 0)
        offset = set_track_offset(self._config, self._track_key, current + delta_ms)
        self.track_offset_changed.emit(self._track_key, offset)
        self._show_offset_feedback(offset)
        self._refresh_media_time()

    def _restore_after_offset_feedback(self) -> None:
        """Put the lyric back after the offset readout.

        A bound method, not a lambda: PyQt holds the receiver weakly for a bound
        method, so the connection dies with the widget. A lambda is held strongly
        and keeps firing into a deleted C++ object, which segfaults."""
        self._on_frame(self._state.frame)

    def _show_offset_feedback(self, offset_ms: int) -> None:
        line = LyricLine(0, "offset-feedback", 0.0, 1e9, t("overlay.offset.value").format(offset=offset_ms), "", ())
        self._current.set_line(line, False)
        self._feedback_timer.start(1200)


    def _apply_blur(self) -> None:
        """Blur the compositor content behind the pill for the frosted-glass style;
        no-op where no blur protocol exists, leaving the translucent fill."""
        self._surface.apply_blur()

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        # The container resizes as the pill/lyric changes size; keep the input
        # region matched to it. This fixes the initially oversized region before
        # the first frame shrinks the pill to its real size.
        if a0 is self._container and a1 is not None:
            if a1.type() in {QEvent.Type.Move, QEvent.Type.Resize}:
                # The rounded panel antialiases one pixel beyond the container's
                # geometry. Repaint the full translucent surface so an old edge
                # cannot survive a layout-driven move or resize.
                self.update()
            if a1.type() == QEvent.Type.Resize:
                self._refresh_input_region()
                QTimer.singleShot(0, self._apply_blur)  # keep the blur region on the pill
        return super().eventFilter(a0, a1)

    # --- drag to reposition (only while unlocked) ---
    #
    # Wayland forbids client-side self.move(); a layer surface is moved by updating
    # its margins. Use BiliHUD's incremental *local* delta — it is accurate ("cursor
    # stops where you release") because the cursor's local position re-settles as the
    # surface follows. (globalPosition() is unreliable for a layer surface on Wayland
    # — it can be off by half a screen — which is why BiliHUD avoids it.) To fix the
    # big-font flicker we commit via the bridge and skip the Qt repaint, so the heavy
    # lyric text isn't re-rendered every frame.

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is not None and not self._passthrough and a0.button() == Qt.MouseButton.LeftButton:
            local = a0.position().toPoint()
            global_position = a0.globalPosition().toPoint()
            mode = self._surface.begin_drag(local, global_position)
            if mode is not DragMode.MANUAL:
                super().mousePressEvent(a0)
                return
            a0.accept()
        else:
            super().mousePressEvent(a0)

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is not None and self._dragging and a0.buttons() & Qt.MouseButton.LeftButton:
            screen = self._target_screen()
            if screen is None:
                a0.accept()
                return
            local = a0.position().toPoint()
            # Keep the surface alive for the entire pointer grab. Recreating it
            # at an output boundary destroys the Wayland pointer grab and makes
            # the next mouse event disappear.
            global_position = a0.globalPosition().toPoint()
            moved = self._surface.update_drag(local, global_position)
            if not moved.succeeded:
                # The surface is where it was, so the drag has not taken effect.
                # Remember that, or the release would save a position the visible
                # window never reached.
                logger.debug("Drag update was not applied: %s", moved.reason)
            # The platform commits the surface, so avoid repainting heavy lyric text.
            a0.accept()
        else:
            super().mouseMoveEvent(a0)

    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:
        if self._dragging:
            cursor_local = a0.position().toPoint() if a0 is not None else None
            release = self._surface.end_drag()
            if release.should_commit:
                self._commit_drag_position(cursor_local)
            elif release.moved:
                # The window never went where the drag asked, so saving that
                # position would put the config and the visible window out of step.
                logger.info(
                    "Not saving the dragged position: %s",
                    self._platform.capabilities.client_positioning_reason,
                )
            if a0 is not None:
                a0.accept()
        else:
            super().mouseReleaseEvent(a0)

    def _clamp_to_screen(
        self,
        pos: QPoint,
        *,
        screen: ScreenLike | None = None,
        width: int | None = None,
        height: int | None = None,
        allow_partial: bool = True,
    ) -> QPoint:
        target = screen if screen is not None else self._target_screen()
        if target is None:
            return pos
        if width is None or height is None:
            width, height = self._window_size()
        return self._surface.clamp_to_screen(
            pos,
            screen=target,
            width=width,
            height=height,
            allow_partial=allow_partial,
        )

    def _commit_drag_position(self, cursor_local: QPoint | None = None) -> None:
        """Persist the output and edge placement after a drag.

        The layer surface can cross output boundaries while it is grabbed. Only
        after release do we select the output under the cursor and remap the
        surface, when necessary, so the next drag starts with that output as its
        local coordinate system.
        """
        result = self._surface.commit_drag_position(
            cursor_local,
            surface_screen=self._target_screen(),
            screens=QGuiApplication.screens(),
            window_size=self._window_size(),
        )
        if result is not None:
            self.position_changed.emit(result.margin_edge, result.margin_x, result.screen_name)

    @property
    def passthrough(self) -> bool:
        return self._passthrough

    @property
    def controller(self) -> LayerShellBridge:
        return self._controller

    # --- painting ---

    def paintEvent(self, a0: QPaintEvent | None) -> None:  # noqa: ARG002
        if not self._should_paint_panel():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self._panel_base_color()
        # Opacity slider drives the fill for every style, including frosted: lower
        # it to let more of the KWin backdrop-blur show through, raise it for a
        # heavier tint. (It used to be capped for frost, so the slider did nothing
        # over its upper range.)
        color.setAlpha(self._panel_alpha())
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self._container.geometry(), PILL_RADIUS, PILL_RADIUS)

    def _text_colors(self) -> tuple[QColor, QColor, str]:
        """Return text colors selected by the appearance policy."""
        return self._appearance.text_colors(self._config)

    def _panel_base_color(self) -> QColor:
        """Return the configured panel fill color."""
        return self._appearance.panel_base_color(self._config)

    def _should_paint_panel(self) -> bool:
        """Return whether the current appearance includes a panel fill."""
        return self._appearance.should_paint_panel(self._config)

    def _panel_alpha(self) -> int:
        """Return the panel fill alpha selected by the appearance policy."""
        return self._appearance.panel_alpha(self._config)

    def reset(self) -> None:
        self._on_frame(EMPTY_FRAME)
