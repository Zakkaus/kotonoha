"""The one card that says what is playing and which lyrics it currently has."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ...display.models import LyricsDisplayStatus
from ...lyrics.search import LyricsSearchQuery
from ...strings import Translator
from .lyrics_search_model import format_duration, readable
from .widgets import ElidingLabel, ScrollingLabel

# How wide a published title may run before it shortens. Past this the length
# beside it would be pushed out of the reader's way.
_TITLE_MAX_WIDTH = 360


class TrackHeader(QFrame):
    """Name the track on one side and the lyrics in use on the other.

    The player is not the only thing that knows about the track: a browser
    reports a page title and nothing else, while the lyric document already
    chosen carries the artist and the album. Whatever the player left blank is
    filled from there.
    """

    def __init__(
        self,
        query: LyricsSearchQuery,
        status: LyricsDisplayStatus,
        translator: Translator,
        status_band: QWidget,
    ) -> None:
        super().__init__()
        self._translator = translator
        self._status = status
        self.setObjectName("trackMeta")
        row = QHBoxLayout(self)
        # The same left inset the search fields below use, so the card's first
        # character and the first field sit on one line.
        row.setContentsMargins(12, 10, 14, 10)
        row.setSpacing(0)
        identity = QVBoxLayout()
        identity.setSpacing(2)
        # A player that reports no artist should not leave a dash standing where a
        # name would be: the line is simply not there.
        identity.addLayout(self._title_row(query, status))
        artist = query.artist or (status.lyrics_artist or "")
        if artist:
            identity.addWidget(self._line(artist, "trackArtist"))
        album = readable(query.album or (status.lyrics_album or ""))
        if album:
            name = ElidingLabel()
            name.setObjectName("trackAlbum")
            name.setText(album)
            name.setToolTip(album)
            identity.addWidget(name)
        row.addLayout(identity, 2)
        row.addWidget(status_band, 3)

    def _title_row(self, query: LyricsSearchQuery, status: LyricsDisplayStatus) -> QHBoxLayout:
        """Put the length beside the song name, where it is read rather than found.

        Length is how a reader tells one recording of a song from another, so it
        belongs on the line the eye lands on first. Below the album it was both
        small and last, and an album name long enough pushed it off the card.
        """
        row = QHBoxLayout()
        row.setSpacing(10)
        title = query.title or (status.lyrics_title or "")
        if title:
            # A published title can carry a subtitle, a version and a guest credit.
            # It shortens; the length beside it does not, or the field that tells
            # two recordings apart would be the one that disappears.
            # Sized to the words up to a cap, not to the card: stretched, the
            # length ended up pinned to the far edge with a gap where the name
            # stopped, which is the one place a reader does not look for it.
            # Scrolled rather than shortened: the title is the one field a reader
            # opened this window to check, and half of it answers nothing.
            name = ScrollingLabel()
            name.setObjectName("trackTitle")
            name.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            name.setMaximumWidth(_TITLE_MAX_WIDTH)
            name.setText(title)
            name.setToolTip(title)
            row.addWidget(name, 0)
        row.addWidget(self._line(format_duration(query.duration_s, self._translator), "trackLength"))
        # Room after the length so it never sits against the rule beside it.
        row.addSpacing(12)
        row.addStretch(1)
        return row

    def _line(self, value: str, name: str) -> QLabel:
        """Build one selectable, non-wrapping line of the track identity."""
        label = QLabel(value)
        label.setObjectName(name)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setWordWrap(False)
        return label


__all__ = ["TrackHeader"]
