"""The search window's own surface rules, extending the shared settings skin.

theme.py owns what every settings window looks like; this owns the parts only the
result window has — its track band, its dense table, and its two commands.
"""

from __future__ import annotations

from PyQt6.QtGui import QColor

from . import theme


def search_window_skin(accent: str, theme_name: str, frosted: bool, opacity: float) -> str:
    """Return the stylesheet for one search window in the theme it was opened in."""
    palette = theme._PALETTES[theme_name]
    card_background = theme._card_background(theme_name, frosted, opacity)
    # 42 was faint enough to be lost against the alternating row colour.
    # Neutral, like the sidebar: the accent marks the row with its rail, and a row
    # washed in colour competes with the one control that acts.
    text = QColor(str(palette["TEXT"]))
    selected_bg = f"rgba({text.red()}, {text.green()}, {text.blue()}, 26)"
    return theme._skin(accent, theme_name, frosted, opacity) + f"""
QDialog#lyricsSearchDialog {{ background: transparent; }}
QFrame#trackMeta {{
background: {card_background};
border: 1px solid {palette["CARD_BORDER"]};
border-radius: 10px;
}}
/* The status shares the header card now; a rule separates it from the track. */
QFrame#lyricsStatus {{ background: transparent; border: none; border-left: 1px solid {palette["CARD_BORDER"]}; }}
QLabel#trackTitle {{ color: {palette["TEXT_STRONG"]}; font-size: 15pt; font-weight: 600; }}
QLabel#trackArtist {{ color: {palette["TEXT"]}; }}
QLabel#trackAlbum {{ color: {palette["TEXT_DIM"]}; }}
/* Beside the name, not under the album: length is how one recording of a song
   is told from another. */
QLabel#trackLength {{ color: {palette["TEXT"]}; font-size: 12pt; }}
/* A section title has to win against the table headers under it, which are
   themselves bold, so weight alone does not separate them. */
QLabel#sectionTitle {{
    color: {palette["TEXT_STRONG"]};
    font-size: 12pt;
    /* 600, not 700: a glyph cannot be drawn as heavy as a bold face, so the two
       met in the middle rather than the text pulling away from its mark. */
    font-weight: 600;
    padding: 2px 0;
}}
QLabel#fieldLabel, QLabel#metaLabel {{ color: {palette["TEXT_DIM"]}; }}
QLabel#metaValue {{ color: {palette["TEXT_STRONG"]}; font-weight: 600; }}
QTableView#lyricsSearchTable,
QTableView#lyricsSearchTable > QWidget#qt_scrollarea_viewport {{
background: {card_background};
border: 1px solid {palette["LIST_BORDER"]};
border-radius: 10px;
color: {palette["TEXT"]};
outline: none;
selection-background-color: {selected_bg};
selection-color: {palette["TEXT_STRONG"]};
alternate-background-color: {palette["FIELD_BG"]};
}}
QTableView#lyricsSearchTable::item {{ padding: 7px 8px; border: none; }}
QHeaderView::section {{
background: {palette["FIELD_BG"]};
color: {palette["TEXT_DIM"]};
border: none;
border-bottom: 1px solid {palette["FIELD_BORDER"]};
padding: 10px 8px;
}}
QHeaderView {{ background: transparent; }}
QFrame#searchPanel {{
background: {card_background};
border: 1px solid {palette["CARD_BORDER"]};
border-radius: 10px;
}}
QPushButton#searchButton {{ background: {accent}; color: {palette["GLYPH_ON_ACCENT"]}; border-color: {accent}; }}
QPushButton#searchButton:hover {{ background: {accent}; border-color: {accent}; }}
QPushButton#applyButton {{ background: {accent}; color: {palette["GLYPH_ON_ACCENT"]}; border-color: {accent}; }}
QPushButton#applyButton:hover {{ background: {accent}; border-color: {accent}; }}
QLabel#searchError {{ color: #E56B6F; }}
"""
