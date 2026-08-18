"""Bounds on what an untrusted lyric payload is allowed to cost.

Every provider here fetches from a third party over the network, and one of them
also decompresses what it receives. A timeout bounds how long a response may take,
not how large it may become: a server that streams steadily stays well inside the
limit while the buffered body grows without end, and a compressed body is smaller
still on the wire than in memory. So size is bounded separately, in one place, and
the providers say what they are reading rather than each carrying its own ceiling.
"""

from __future__ import annotations

import json
import zlib
from typing import Any

import aiohttp

#: Lyrics for one song are a few kilobytes; a search result is a few hundred.
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
#: The decompressed form of a lyric payload, which the wire size does not bound.
MAX_DECOMPRESSED_BYTES = 4 * 1024 * 1024


async def read_capped(response: aiohttp.ClientResponse, source: str) -> bytes:
    """Return the body, refusing one larger than :data:`MAX_RESPONSE_BYTES`."""
    body = await response.content.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError(f"{source} response exceeded {MAX_RESPONSE_BYTES} bytes")
    return body


async def read_json_capped(response: aiohttp.ClientResponse, source: str) -> Any:
    """Return the body parsed as JSON, refusing an oversized one.

    Used instead of ``response.json()``, which buffers whatever arrives.
    """
    body = await read_capped(response, source)
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{source} response is not JSON: {exc}") from exc


def decompress_capped(data: bytes, source: str) -> bytes:
    """Inflate ``data``, refusing a stream that expands past the ceiling.

    zlib.decompress allocates whatever the stream unpacks to. Measured on this
    project's own KRC path, 203KB of valid compressed body expanded to 200MB and
    took the process's resident size with it, so the output is read in bounded
    steps and a stream with more to give is rejected rather than finished.
    """
    machine = zlib.decompressobj()
    out = machine.decompress(data, MAX_DECOMPRESSED_BYTES)
    if not machine.eof or machine.unconsumed_tail:
        raise ValueError(f"{source} payload expands past {MAX_DECOMPRESSED_BYTES} bytes")
    return out
