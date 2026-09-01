"""Control icons rendered from open-source SVG (Lucide, ISC license).

Lucide <https://lucide.dev> stroke icons, recoloured and rasterised via QtSvg —
crisp monochrome lock / unlock / settings glyphs (no emoji, no hand-drawn paths).
"""

from __future__ import annotations

from PyQt6.QtCore import QByteArray
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

ICON_SIZE = 64

_SVG_HEAD = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
)

# Lucide: lock
_LOCK = _SVG_HEAD + (
    '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>'
)
# Lucide: lock-open
_UNLOCK = _SVG_HEAD + (
    '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 9.9-1"/></svg>'
)
# Lucide: settings-2 (sliders — simpler and robust to render)
_SETTINGS = _SVG_HEAD + (
    '<path d="M20 7h-9"/><path d="M14 17H5"/>'
    '<circle cx="17" cy="17" r="3"/><circle cx="7" cy="7" r="3"/></svg>'
)
_SEARCH = _SVG_HEAD + '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>'
# Lucide: sliders-horizontal, image, type, panel-top, sparkles, align-left, move, list-music.
# One nav glyph per settings page, same set and stroke weight as the rest of this file.
_NAV = {
    "tab.general": '<path d="M21 4H3"/><path d="M21 12H9"/><path d="M21 20H7"/>'
    '<path d="M7 4v4"/><path d="M9 12v4"/><path d="M5 20v-4"/>',
    "tab.icon": '<rect width="18" height="18" x="3" y="3" rx="2"/>'
    '<circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
    "tab.text": '<path d="M4 7V5h16v2"/><path d="M12 5v14"/><path d="M9 19h6"/>',
    "tab.panel": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/>',
    "tab.effects": '<path d="M12 3v4"/><path d="M12 17v4"/><path d="M3 12h4"/><path d="M17 12h4"/>'
    '<path d="m6 6 2.5 2.5"/><path d="m15.5 15.5 2.5 2.5"/><path d="m18 6-2.5 2.5"/>'
    '<path d="m8.5 15.5-2.5 2.5"/>',
    "tab.lyrics": '<path d="M4 6h16"/><path d="M4 12h10"/><path d="M4 18h13"/>',
    "tab.position": '<path d="M12 3v18"/><path d="M3 12h18"/><path d="m9 6 3-3 3 3"/>'
    '<path d="m9 18 3 3 3-3"/><path d="m6 9-3 3 3 3"/><path d="m18 9 3 3-3 3"/>',
    "tab.sources": '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/>'
    '<circle cx="18" cy="16" r="3"/>',
}
_EARLIER = _SVG_HEAD + '<path d="M19 12H5"/><path d="m12 19-7-7 7-7"/></svg>'
_LATER = _SVG_HEAD + '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>'


# Lucide: list
_LIST = _SVG_HEAD + (
    '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/>'
    '<path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/></svg>'
)
_CLEAR = _SVG_HEAD + '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/></svg>'
_NAV_ICON_SIZE = 32


def _render(svg: str, color: str, size: int = ICON_SIZE) -> QIcon:
    """Rasterise one glyph at the size it will be drawn at.

    A stroke rasterised at 64px and scaled down to 16 loses most of its weight to
    resampling: measured at 136 inked pixels of which 24 were opaque, so the glyph
    read as a grey smudge beside text at full strength.
    """
    data = QByteArray(svg.replace("currentColor", color).encode("utf-8"))
    renderer = QSvgRenderer(data)
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    icon = QIcon()
    # Qt generates its own Selected and Active pixmaps by tinting the normal one
    # blue. These glyphs already carry a colour chosen against the surface, so the
    # same pixmap is registered for every mode.
    for mode in (QIcon.Mode.Normal, QIcon.Mode.Selected, QIcon.Mode.Active):
        icon.addPixmap(pixmap, mode)
    return icon


def nav_icon(page_key: str, color: str) -> QIcon:
    """Render the glyph for one settings page, or an empty icon for an unnamed page."""
    body = _NAV.get(page_key)
    # A heavier stroke than the rest of the set. At 16px the standard weight lands
    # on 1.3 pixels and antialiasing spends most of it: 24 opaque pixels of 136,
    # against 118 of 161 at this weight. Partial alpha is what made the glyph grey
    # — on a dark surface a half-covered white pixel is grey, beside a label that
    # is not. Rendered at twice the drawn size so a dense screen has pixels to use.
    head = _SVG_HEAD.replace('stroke-width="2"', 'stroke-width="3"')
    return _render(head + (body or "") + "</svg>", color, _NAV_ICON_SIZE)


def heading_icon(kind: str, color: str) -> QIcon:
    """Render a section-title glyph at the weight the heading beside it carries.

    A heading is set bold, and the set's standard stroke beside it reads as a
    thinner thing that happens to be next to a heavier one.
    """
    body = {"search": _SEARCH, "list": _LIST}[kind]
    return _render(body.replace('stroke-width="2"', 'stroke-width="3"'), color, _NAV_ICON_SIZE)


def list_icon(color: str) -> QIcon:
    """Render the results glyph that titles a table of candidates."""
    return _render(_LIST, color)


def clear_icon(color: str) -> QIcon:
    """Render the clear-field glyph, which Qt's own does not theme."""
    return _render(_CLEAR, color)


def lock_icon(closed: bool, color: str = "#FFFFFF") -> QIcon:
    return _render(_LOCK if closed else _UNLOCK, color)


def settings_icon(color: str = "#FFFFFF") -> QIcon:
    return _render(_SETTINGS, color)


def search_icon(color: str = "#FFFFFF") -> QIcon:
    """Return the monochrome search glyph used by lyric lookup controls."""
    return _render(_SEARCH, color)


def earlier_icon(color: str = "#FFFFFF") -> QIcon:
    return _render(_EARLIER, color)


def later_icon(color: str = "#FFFFFF") -> QIcon:
    return _render(_LATER, color)
