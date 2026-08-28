"""Application services that apply configuration to runtime collaborators."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtWidgets import QApplication

from ..config import Config
from ..display.coordinator import DisplayCoordinator
from ..display.models import (
    DisplayOptions,
    DisplayScript,
    InterludeCountdown,
    InterludeMarkerStyle,
)
from ..i18n import resolve_translation_language
from ..providers.cider_api import CiderApiProvider
from ..providers.mpris import MprisProvider
from ..strings import set_language
from ..tray import KotonohaTray, load_icon
from ..ui.overlay import LyricsOverlay
from .source_gate import SourceOwnershipCoordinator


@dataclass(frozen=True, slots=True)
class RuntimeConfigChanges:
    """Side effects the application controller must schedule after applying config."""

    cider_token_changed: bool
    cider_token: str


class RuntimeConfigApplier:
    """Apply one validated config to all already-composed runtime collaborators."""

    def __init__(
        self,
        app: QApplication,
        display: DisplayCoordinator,
        overlay: LyricsOverlay,
        tray: KotonohaTray,
        mpris: MprisProvider,
        cider: CiderApiProvider,
        ownership: SourceOwnershipCoordinator,
    ) -> None:
        self._app = app
        self._display = display
        self._overlay = overlay
        self._tray = tray
        self._mpris = mpris
        self._cider = cider
        self._ownership = ownership

    def apply(self, previous: Config, current: Config) -> RuntimeConfigChanges:
        """Refresh runtime collaborators and report deferred credential work."""
        self._display.set_options(display_options(current))
        self._overlay.apply_config(current)
        self._overlay.activate_layer_shell()
        self._tray.set_passthrough_checked(current.passthrough)
        self._app.setWindowIcon(load_icon(current.window_icon_name, accent=current.accent_start))
        self._tray.set_icon_name(current.icon_name, current.accent_start)
        self._mpris.set_lyrics_sources(current.lyrics_sources)
        self._cider.set_enabled("cider" in current.lyrics_sources)
        self._cider.set_token(current.cider_api_token)
        self._mpris.set_player_lock(current.player_lock)
        self._mpris.set_cache_enabled(current.cache_enabled)
        self._mpris.set_prefer_best(current.prefer_best_lyrics)
        self._mpris.set_fuzzy(current.fuzzy_match)
        self._ownership.set_display_sources(current.display_sources)
        set_language(current.ui_language)

        previous_language = resolve_translation_language(previous.translation_language)
        current_language = resolve_translation_language(current.translation_language)
        if current_language != previous_language:
            self._cider.set_translation_language(current_language)
        return RuntimeConfigChanges(
            cider_token_changed=current.cider_api_token != previous.cider_api_token,
            cider_token=current.cider_api_token,
        )


def display_options(config: Config) -> DisplayOptions:
    """Build the immutable display options consumed by the display coordinator."""
    return DisplayOptions(
        lead_ms=config.lead_ms,
        track_offsets_ms=dict(config.track_offsets),
        lyrics_script=DisplayScript(config.lyrics_script.value),
        interlude_style=InterludeMarkerStyle(config.interlude_style.value),
        interlude_countdown=InterludeCountdown(config.interlude_countdown.value),
    )


__all__ = ["RuntimeConfigApplier", "RuntimeConfigChanges", "display_options"]
