"""HTTP session construction for network lyric providers."""

from __future__ import annotations

import aiohttp

from ..lyrics.http import AioHttpLyricsSession


def new_lyrics_session() -> AioHttpLyricsSession:
    """Create the shared, bounded HTTP session used by lyric sources.

    The session has a generous total timeout because each provider supplies its
    own tighter request budget. A dummy cookie jar keeps NetEase search responses
    independent across requests; its first response otherwise sets a cookie that
    can make later searches return unrelated popular songs.
    """
    return AioHttpLyricsSession(
        aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20.0, connect=5.0),
            cookie_jar=aiohttp.DummyCookieJar(),
        )
    )


__all__ = ["new_lyrics_session"]
