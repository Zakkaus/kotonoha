"""Pure appearance policy used by the Qt lyrics overlay."""

from __future__ import annotations

from PyQt6.QtGui import QColor

from ..config import Config

_FALLBACK_FAMILIES = (
    "Noto Sans CJK SC",
    "Noto Sans CJK JP",
    "Noto Sans CJK KR",
    "Source Han Sans SC",
    "Microsoft YaHei",
    "PingFang SC",
    "Segoe UI",
    "sans-serif",
)


class OverlayAppearance:
    """Own color, font, and panel-visibility decisions for one overlay config."""

    def font_families(self, config: Config) -> list[str]:
        """Return the selected family followed by the CJK fallback chain."""
        chosen = config.font_family.split(",")[0].strip().strip("'\"")
        families = [chosen] if chosen else []
        for name in _FALLBACK_FAMILIES:
            if name not in families:
                families.append(name)
        return families

    def text_colors(self, config: Config) -> tuple[QColor, QColor, str]:
        """Return lyric base, shadow, and context-label colors for the panel."""
        if config.panel_style == "white":
            return QColor(28, 30, 36, 235), QColor(255, 255, 255, 90), "rgba(20,22,28,150)"
        return QColor(255, 255, 255, 95), QColor(0, 0, 0, 170), "rgba(255,255,255,120)"

    def panel_base_color(self, config: Config) -> QColor:
        """Return the panel fill before its configured opacity is applied."""
        accent = QColor(config.accent_start)
        if config.panel_style == "white":
            return accent.lighter(190) if config.panel_accent_tint else QColor(244, 245, 248)
        if config.panel_style == "frost":
            if config.panel_accent_tint:
                return QColor(
                    accent.red() * 22 // 100 + 8,
                    accent.green() * 22 // 100 + 10,
                    accent.blue() * 22 // 100 + 16,
                )
            return QColor(26, 30, 40)
        if config.panel_accent_tint:
            return QColor(
                accent.red() * 30 // 100,
                accent.green() * 30 // 100,
                accent.blue() * 30 // 100,
            )
        return QColor(15, 17, 22)

    def should_paint_panel(self, config: Config) -> bool:
        """Return whether this panel style draws a translucent background."""
        return config.panel_style in ("pill", "white", "frost")

    def panel_alpha(self, config: Config) -> int:
        """Convert the active panel opacity setting to a Qt alpha value."""
        opacity = config.frost_opacity if config.panel_style == "frost" else config.opacity
        return max(0, min(255, round(255 * opacity)))


__all__ = ["OverlayAppearance"]
