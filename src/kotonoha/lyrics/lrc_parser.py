"""Parse standard LRC (line-timed) lyrics and merge a translation track.

Used as the fallback when a song has no word-timed (YRC) lyrics, and to attach
Netease ``tlyric`` (also LRC) onto the main lines by timestamp.
"""

from __future__ import annotations

import re

from .models import LyricLine
from .translation import TranslationMerger

# [mm:ss], [mm:ss.xx] or [mm:ss.xxx]; a line may carry several time tags.
_TIME = re.compile(r"\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
# The standard shift tag, in milliseconds and signed. Per the format's own
# wording a "+" value causes the lyrics to appear sooner, so it is subtracted
# from each timestamp rather than added. A sidecar written against a different
# rip is commonly a second or two out without it.
_OFFSET = re.compile(r"(?i)^\s*\[offset:\s*([+-]?\d{1,6})\s*\]\s*$", re.MULTILINE)
_MAX_OFFSET_S = 60.0


def _offset_seconds(text: str) -> float:
    matches = _OFFSET.findall(text)
    if not matches:
        return 0.0
    seconds = int(matches[-1]) / 1000.0  # the last tag wins, as players do
    # A tag far outside plausible correction is junk, not an instruction.
    return seconds if abs(seconds) <= _MAX_OFFSET_S else 0.0


#: More timed lines than any song has. The byte budget upstream still allows a
#: response of tens of thousands of valid tags, and each one becomes an object the
#: overlay holds and the cache stores; a lyric sheet runs to a few hundred.
MAX_LINES = 5000


def parse_lrc(text: str) -> list[LyricLine]:
    """Return timed lines from an LRC body, ignoring anything past MAX_LINES."""
    offset = _offset_seconds(text)
    entries: list[tuple[float, str]] = []
    for raw in text.splitlines():
        if len(entries) >= MAX_LINES:
            break
        tags = list(_TIME.finditer(raw))
        if not tags:
            continue
        content = raw[tags[-1].end() :].strip()
        if not content:
            continue
        for tag in tags:
            minutes = int(tag.group(1))
            seconds = int(tag.group(2))
            frac = tag.group(3) or ""
            millis = int((frac + "000")[:3]) if frac else 0
            start = minutes * 60 + seconds + millis / 1000.0 - offset
            entries.append((max(0.0, start), content))

    entries.sort(key=lambda e: e[0])
    out: list[LyricLine] = []
    for i, (start, content) in enumerate(entries):
        end = entries[i + 1][0] if i + 1 < len(entries) else start + 5.0
        out.append(
            LyricLine(index=i, id=f"L{i}", start=start, end=end, text=content, translation="", words=())
        )
    return out


def merge_translation(base: list[LyricLine], translation: list[LyricLine], tolerance: float = 0.4) -> list[LyricLine]:
    """Compatibility wrapper for timestamp alignment."""
    return list(TranslationMerger(tolerance).merge_by_timestamp(base, translation))
