"""Local WebSocket server for canonical external lyric adapters."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from aiohttp import WSMsgType, web

from .display.coordinator import DisplayCoordinator
from .lyrics.ownership import SourceOwnershipCoordinator
from .lyrics.protocol import AdapterClock, AdapterProtocolDecoder, AdapterProtocolError, AdapterSnapshot

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 28745
WS_PATH = "/kotonoha/adapter"
_POST_CLIENT_ID = 0


@dataclass
class _AdapterSession:
    """Ordering state for one connected adapter client."""

    last_sequence: int | None = None
    track_ref: str | None = None


def _is_local_origin(request: web.Request) -> bool:
    """Return whether a local adapter may submit data to the overlay."""
    origin = request.headers.get("Origin")
    if not origin:
        return True
    host = urlparse(origin).hostname
    return host in {"localhost", "127.0.0.1", "::1"}


class AdapterReceiver:
    """Own the external adapter socket and publish canonical display frames."""

    def __init__(
        self,
        display: DisplayCoordinator,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        ownership: SourceOwnershipCoordinator,
        decoder: AdapterProtocolDecoder | None = None,
    ) -> None:
        self._display = display
        self._host = host
        self._port = port
        self._ownership = ownership
        self._decoder = decoder if decoder is not None else AdapterProtocolDecoder()
        self._clients: set[web.WebSocketResponse] = set()
        self._sessions: dict[int, _AdapterSession] = {}
        self._runner: web.AppRunner | None = None

    def build_app(self) -> web.Application:
        """Build the HTTP application without starting a listener."""
        app = web.Application()
        app.router.add_get(WS_PATH, self._handle_ws)
        app.router.add_post(WS_PATH, self._handle_post)
        return app

    async def start(self) -> None:
        """Bind the local adapter endpoint and own its runner."""
        if self._runner is not None:
            return
        runner = web.AppRunner(self.build_app())
        await runner.setup()
        site = web.TCPSite(runner, self._host, self._port)
        try:
            await site.start()
        except OSError:
            await runner.cleanup()
            raise
        self._runner = runner
        logger.info("Adapter receiver listening on ws://%s:%d%s", self._host, self._port, WS_PATH)

    async def stop(self) -> None:
        """Close all external connections and release the listening runner."""
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    def ingest(self, raw_text: str, *, client_id: int) -> bool:
        """Decode and publish one canonical adapter message."""
        try:
            message = self._decoder.decode_text(raw_text, observed_at=time.monotonic())
        except AdapterProtocolError as exc:
            logger.debug("Dropped invalid adapter frame (%d bytes): %s", len(raw_text), exc)
            return False

        session = self._sessions.setdefault(client_id, _AdapterSession())
        if session.last_sequence is not None and message.sequence <= session.last_sequence:
            logger.debug("Dropped stale adapter sequence %d for client %s", message.sequence, client_id)
            return False

        if isinstance(message, AdapterSnapshot):
            accepted = self._publish_snapshot(message, client_id, session)
        elif isinstance(message, AdapterClock):
            accepted = self._publish_clock(message, client_id, session)
        else:
            raise TypeError(f"unsupported adapter message type: {type(message).__name__}")
        if accepted:
            session.last_sequence = message.sequence
        return accepted

    def _publish_snapshot(self, message: AdapterSnapshot, client_id: int, session: _AdapterSession) -> bool:
        session.track_ref = message.playback.track.track_ref if message.playback.track is not None else None
        self._ownership.observe(client_id, message.playback, message.document)
        if not self._ownership.accepts(client_id):
            return True
        self._display.publish(message.playback, message.document)
        return True

    def _publish_clock(self, message: AdapterClock, client_id: int, session: _AdapterSession) -> bool:
        if message.track_ref != session.track_ref:
            logger.debug("Dropped adapter clock for a different track from client %s", client_id)
            return False
        accepted = self._ownership.observe_clock(
            client_id,
            message.track_ref,
            message.position_s,
            message.status.value == "Playing",
        )
        if not accepted:
            return False
        if self._ownership.accepts(client_id):
            self._display.tick(message.position_s, message.status.value == "Playing")
        return True

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        if not _is_local_origin(request):
            raise web.HTTPForbidden
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        client_id = id(ws)
        self._clients.add(ws)
        logger.debug("External adapter connected")
        try:
            async for message in ws:
                if message.type == WSMsgType.TEXT:
                    self.ingest(message.data, client_id=client_id)
                elif message.type == WSMsgType.ERROR:
                    logger.debug("Adapter connection error: %s", ws.exception())
                    break
        finally:
            self._clients.discard(ws)
            self._sessions.pop(client_id, None)
            self._ownership.drop_client(client_id)
        logger.debug("External adapter disconnected")
        return ws

    async def _handle_post(self, request: web.Request) -> web.Response:
        if not _is_local_origin(request):
            return web.Response(status=403)
        try:
            body = await request.text()
        except UnicodeDecodeError:
            logger.debug("Dropped an adapter frame that is not UTF-8")
            return web.Response(status=400)
        # POST is the local debug/integration route, so all requests intentionally
        # share one logical client session and therefore one sequence namespace.
        return web.Response(status=204 if self.ingest(body, client_id=_POST_CLIENT_ID) else 400)


__all__ = ["AdapterReceiver", "DEFAULT_HOST", "DEFAULT_PORT", "WS_PATH"]
