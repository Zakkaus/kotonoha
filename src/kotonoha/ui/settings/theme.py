"""Theme palette and stylesheet generation for the settings window."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QGuiApplication

_QSS = """
QWidget { color: %TEXT%; font-family: 'Inter', 'Segoe UI', 'Microsoft YaHei', sans-serif; font-size: 13px; }
QLabel { background: transparent; }
QLabel#hint { color: %HINT%; }
QLabel#dialogTitle { color: %TEXT_STRONG%; font-size: 15px; font-weight: 600; }
QPushButton#closeButton {
    background: transparent; border: none; color: %TEXT_DIM%; font-size: 15px; border-radius: 13px;
}
QPushButton#closeButton:hover { color: %TEXT_STRONG%; background: %ITEM_SEL%; }
/* Left sidebar navigation (a QListWidget#nav) + a stacked content area, instead
   of top tabs — a cleaner settings layout with no tab/box corner clashes. */
QListWidget#nav {
    background: transparent;
    border: none;
    outline: none;
    padding: 2px;
}
QListWidget#nav::item {
    color: %TEXT_DIM%;
    padding: 9px 12px;
    border-radius: 8px;
    margin: 2px 0;
}
QListWidget#nav::item:hover { color: %TEXT_STRONG%; background: %NAV_HOVER%; }
QListWidget#nav::item:selected { color: %TEXT_STRONG%; background: %ACCENT_SOFT%; }
/* Raised content surface (a card) for depth over the base dialog + sidebar. */
QWidget#contentCard { background: %CARD_BG%; border: 1px solid %CARD_BORDER%; border-radius: 12px; }
QScrollArea#settingsPageScroll { background: transparent; border: none; }
QScrollArea#settingsPageScroll > QWidget#qt_scrollarea_viewport { background: transparent; border: none; }
QWidget#qt_scrollarea_vcontainer, QWidget#qt_scrollarea_hcontainer { background: transparent; }
QScrollBar:vertical {
    background: transparent;
    width: 9px;
    margin: 8px 2px;
}
QScrollBar::handle:vertical {
    background: %FIELD_BORDER%;
    min-height: 36px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover { background: %FIELD_BORDER_HOVER%; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
    background: transparent;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QCheckBox { background: transparent; spacing: 8px; }
QCheckBox::indicator, QListWidget::indicator {
    width: 16px; height: 16px;
    border: 1px solid %IND_BORDER%;
    border-radius: 5px;
    background: %IND_BG%;
}
/* Once the indicator is custom-styled, Qt no longer paints the native tick, so
   the checkmark must be supplied explicitly — otherwise checked boxes rendered
   as a bare filled square with no glyph, inconsistently across the dialog. */
QCheckBox::indicator:checked, QListWidget::indicator:checked {
    background: %ACCENT%;
    border-color: %ACCENT%;
    image: url(%CHECK%);
}
/* A disabled checkbox reads as unavailable: dimmed label, muted (non-accent) box. */
QCheckBox:disabled { color: %HINT%; }
QCheckBox::indicator:disabled { border-color: %IND_BORDER%; background: %IND_BG%; }
QCheckBox::indicator:checked:disabled { background: %HINT%; border-color: %HINT%; image: url(%CHECK%); }
/* One field style for every input so combos, spin boxes and the font picker are
   the same height and look uniform. */
QSpinBox, QComboBox, QFontComboBox, QLineEdit {
    background: %FIELD_BG%;
    border: 1px solid %FIELD_BORDER%;
    border-radius: 7px;
    padding: 4px 9px;
    color: %TEXT%;
    min-height: 24px;
    max-height: 24px;  /* combos and spin boxes end up exactly the same height (~34px) */
}
QSpinBox:hover, QComboBox:hover, QFontComboBox:hover, QLineEdit:hover { border-color: %FIELD_BORDER_HOVER%; }
/* Accent focus ring — clear interactive feedback on the control you're editing. */
QSpinBox:focus, QComboBox:focus, QFontComboBox:focus, QLineEdit:focus { border: 1px solid %ACCENT%; }
QSpinBox:disabled, QComboBox:disabled { color: %TEXT_DIM%; }
/* Keep the popup item rules as a fallback for styles that parent the view under
   the combo. Standalone popup views receive the same rules explicitly in the
   dialog because a dialog stylesheet cannot match a top-level popup sibling. */
QComboBox, QFontComboBox { combobox-popup: 0; }
QComboBox::drop-down, QFontComboBox::drop-down {
    subcontrol-origin: padding; subcontrol-position: center right;
    border: none; width: 22px;
}
QComboBox::down-arrow, QFontComboBox::down-arrow { image: url(%CHEV_DOWN%); width: 12px; height: 12px; }
/* Compact, borderless spin buttons with the same chevrons, so a spin box is the
   same height as a combo instead of a tall two-button control. */
QSpinBox::up-button, QSpinBox::down-button {
    subcontrol-origin: border; border: none; background: transparent; width: 20px;
}
QSpinBox::up-button { subcontrol-position: top right; }
QSpinBox::down-button { subcontrol-position: bottom right; }
QSpinBox::up-arrow { image: url(%CHEV_UP%); width: 11px; height: 11px; }
QSpinBox::down-arrow { image: url(%CHEV_DOWN%); width: 11px; height: 11px; }
QComboBox QAbstractItemView {
    background: %POPUP_BG%;
    color: %TEXT%;
    border: 1px solid %FIELD_BORDER%;
    border-radius: 8px;
    padding: 4px;
    selection-background-color: %ACCENT%;
    selection-color: #FFFFFF;
    outline: none;
}
QListWidget {
    background: %LIST_BG%;
    border: 1px solid %LIST_BORDER%;
    border-radius: 10px;
    outline: none;
    padding: 6px;
}
QListWidget::item { padding: 8px 10px; border-radius: 7px; }
QListWidget::item:selected { background: %ITEM_SEL%; color: %TEXT_STRONG%; }
/* De-boxed: no list border/background so the icons don't read as a nested panel.
   Selection is a clean accent ring around the chosen icon, not a grey slab. */
QListWidget#iconPicker { background: transparent; border: none; padding: 2px; }
QListWidget#iconPicker::item {
    padding: 0;
    margin: 4px;
    border: 2px solid transparent;
    border-radius: 12px;
}
QListWidget#iconPicker::item:hover { border-color: %FIELD_BORDER_HOVER%; }
QListWidget#iconPicker::item:selected { background: transparent; border: 2px solid %ACCENT%; }
QPushButton {
    background: %BTN_BG%;
    border: 1px solid %FIELD_BORDER%;
    border-radius: 7px;
    padding: 6px 18px;
    color: %TEXT_STRONG%;
}
QPushButton:hover { background: %BTN_HOVER%; }
QPushButton:pressed { background: %BTN_PRESSED%; }
/* The lists already suppress Qt's dotted focus rectangle; the buttons did not, so
   the dialog's default button wore one from the moment it opened. Suppressed here
   too, and replaced with the accent border — removing the indicator outright would
   leave keyboard focus invisible. */
QPushButton:focus { outline: none; border: 1px solid %ACCENT%; }
"""

# Colour tokens per theme. String values fill %TOKEN% in the QSS; the window_* RGBA
# tuples paint the frameless dialog background in paintEvent.
_PALETTES: dict[str, dict[str, object]] = {
    "dark": {
        "TEXT": "#E6E6E8", "TEXT_STRONG": "#FFFFFF", "TEXT_DIM": "rgba(255,255,255,140)",
        "HINT": "rgba(255,255,255,120)",
        "PANE_BG": "rgba(255,255,255,8)", "PANE_BORDER": "rgba(255,255,255,20)",
        # Raised content surface (a card) over the base dialog + sidebar, for depth.
        "CARD_BG": "rgba(255,255,255,7)", "CARD_BORDER": "rgba(255,255,255,14)",
        "NAV_HOVER": "rgba(255,255,255,12)",
        "FIELD_BG": "rgba(255,255,255,18)", "FIELD_BORDER": "rgba(255,255,255,32)",
        "FIELD_BORDER_HOVER": "rgba(255,255,255,80)", "POPUP_BG": "#1e2027",
        "IND_BORDER": "rgba(255,255,255,60)", "IND_BG": "rgba(255,255,255,15)",
        "LIST_BG": "rgba(255,255,255,10)", "LIST_BORDER": "rgba(255,255,255,18)",
        "ITEM_SEL": "rgba(255,255,255,26)",
        "BTN_BG": "rgba(255,255,255,20)", "BTN_HOVER": "rgba(255,255,255,40)",
        "BTN_PRESSED": "rgba(255,255,255,60)",
        "window_bg": (20, 22, 28, 240), "window_border": (255, 255, 255, 30),
    },
    "light": {
        "TEXT": "#24272B", "TEXT_STRONG": "#0E1013", "TEXT_DIM": "rgba(0,0,0,135)",
        "HINT": "rgba(0,0,0,115)",
        "PANE_BG": "rgba(0,0,0,4)", "PANE_BORDER": "rgba(0,0,0,14)",
        # A white content card over the light-grey dialog + sidebar, for depth.
        "CARD_BG": "#FFFFFF", "CARD_BORDER": "rgba(0,0,0,12)",
        "NAV_HOVER": "rgba(0,0,0,7)",
        "FIELD_BG": "rgba(0,0,0,6)", "FIELD_BORDER": "rgba(0,0,0,28)",
        # Keep popups close to the light window surface; a pure white native
        # popup reads as a disconnected rectangle over the frosted dialog.
        "FIELD_BORDER_HOVER": "rgba(0,0,0,65)", "POPUP_BG": "#E8EAED",
        "IND_BORDER": "rgba(0,0,0,50)", "IND_BG": "rgba(0,0,0,6)",
        "LIST_BG": "rgba(0,0,0,4)", "LIST_BORDER": "rgba(0,0,0,14)",
        "ITEM_SEL": "rgba(0,0,0,12)",
        "BTN_BG": "rgba(0,0,0,7)", "BTN_HOVER": "rgba(0,0,0,14)",
        "BTN_PRESSED": "rgba(0,0,0,22)",
        "window_bg": (245, 246, 249, 243), "window_border": (0, 0, 0, 32),
    },
}

# White checkmark painted over a checked indicator. Qt's stylesheet url() does
# NOT decode data: URIs (it only loads file/resource paths), so this must be a
# real bundled file — an inline data URI silently renders nothing, leaving a bare
# filled square. Qt's SVG image plugin renders it. (White reads fine on every
# accent colour, in both themes, since the checked box is filled with the accent.)
# The package-wide assets directory is shared by the tray and Settings UI; keep
# this lookup anchored at the package root after the Settings modules move.
_ASSETS_PATH = Path(__file__).parents[2] / "assets"
_CHECKMARK_PATH = _ASSETS_PATH / "checkmark.svg"
# Mid-grey chevrons for combo/spin arrows — one asset reads fine on both themes.
_CHEVRON_DOWN_PATH = _ASSETS_PATH / "chevron-down.svg"
_CHEVRON_UP_PATH = _ASSETS_PATH / "chevron-up.svg"



def _resolve_theme(value: str) -> str:
    """Map the config theme ("auto"/"light"/"dark") to a concrete "light"/"dark".
    "auto" follows the system colour scheme (Qt 6.5+), defaulting to dark."""
    if value in ("light", "dark"):
        return value
    app = cast(QGuiApplication | None, QGuiApplication.instance())
    hints = app.styleHints() if app is not None else None
    scheme = hints.colorScheme() if hints is not None else None
    return "light" if scheme == Qt.ColorScheme.Light else "dark"


def _card_background(theme: str, frosted: bool = False, opacity: float = 1.0) -> str:
    """Return the effective content-card background for a settings surface."""
    if frosted:
        return "rgba(255, 255, 255, 120)" if theme == "light" else "rgba(255, 255, 255, 16)"
    if opacity < 0.999 and theme == "light":
        return f"rgba(255, 255, 255, {max(0, min(255, round(255 * opacity)))})"
    value = _PALETTES.get(theme, _PALETTES["dark"])["CARD_BG"]
    if not isinstance(value, str):
        raise TypeError("theme card background must be a string")
    return value


def _skin(accent: str, theme: str = "dark", frosted: bool = False, opacity: float = 1.0) -> str:
    """Fill the QSS template from the theme palette, accent colour and checkmark.
    When `frosted`, the content card is made translucent so the KWin backdrop-blur
    shows through it instead of reading as a solid block on the frosted window.
    `opacity` (<1) makes the window see-through: the light theme's opaque white card
    is thinned so the desktop shows through it (dark's card is already translucent,
    so its window fill — painted in paintEvent — carries the effect)."""
    palette = dict(_PALETTES.get(theme, _PALETTES["dark"]))
    palette["CARD_BG"] = _card_background(theme, frosted, opacity)
    qss = _QSS
    for token, value in palette.items():
        if isinstance(value, str):
            qss = qss.replace(f"%{token}%", value)
    c = QColor(accent)
    accent_soft = f"rgba({c.red()}, {c.green()}, {c.blue()}, 42)"  # tinted sidebar selection
    return (
        qss.replace("%ACCENT_SOFT%", accent_soft)
        .replace("%ACCENT%", accent)
        .replace("%CHECK%", _CHECKMARK_PATH.as_posix())
        .replace("%CHEV_DOWN%", _CHEVRON_DOWN_PATH.as_posix())
        .replace("%CHEV_UP%", _CHEVRON_UP_PATH.as_posix())
    )


def _popup_skin(accent: str, theme: str = "dark") -> str:
    """Build the item-view stylesheet used by standalone combo-box popups."""
    palette = _PALETTES.get(theme, _PALETTES["dark"])
    popup_background = _popup_background(theme)
    return f"""
QAbstractItemView {{
    background: {popup_background};
    color: {palette["TEXT"]};
    border: 1px solid {palette["FIELD_BORDER"]};
    border-radius: 8px;
    padding: 4px;
    outline: none;
    selection-background-color: {accent};
    selection-color: #FFFFFF;
}}
QAbstractItemView > QWidget#qt_scrollarea_viewport {{
    background: {popup_background};
}}
QAbstractItemView::item {{ padding: 5px 8px; border-radius: 5px; }}
QAbstractItemView::item:hover {{ background: {palette["ITEM_SEL"]}; color: {palette["TEXT_STRONG"]}; }}
QAbstractItemView::item:selected {{ background: {accent}; color: #FFFFFF; }}
QFrame#settingsComboPopupFrame {{ background: {popup_background}; border: none; }}
QWidget#qt_scrollarea_vcontainer, QWidget#qt_scrollarea_hcontainer {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {palette["FIELD_BORDER"]}; min-height: 30px; border-radius: 4px; }}
QScrollBar::handle:vertical:hover {{ background: {palette["FIELD_BORDER_HOVER"]}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; background: transparent; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""


def _popup_background(theme: str) -> str:
    """Return the opaque background used by a standalone combo popup viewport."""
    value = _PALETTES.get(theme, _PALETTES["dark"])["POPUP_BG"]
    if not isinstance(value, str):
        raise TypeError("theme popup background must be a string")
    return value



__all__ = [
    "_CHECKMARK_PATH",
    "_PALETTES",
    "_QSS",
    "_card_background",
    "_popup_background",
    "_popup_skin",
    "_skin",
    "_resolve_theme",
]
