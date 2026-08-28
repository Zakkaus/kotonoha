"""Owned MPRIS playback session, selection, polling, and stabilization."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ..async_task import create_owned_task, wait_for_owned
from ..playback.models import MprisPlayerPort, MprisPropertyChange, PlaybackObservation
from ..players import PlayerInfo
from .mpris_adapter import MprisPlaybackAdapter
from .mpris_session import MprisSessionError
from .mpris_track import TrackCommit, TrackInfo, TrackObservation, TrackStabilizer
from .player_selection import PlayerRecord, PlayerSelector

logger = logging.getLogger(__name__)

MPRIS_PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"


class MprisSessionPort(Protocol):
    """Session operations owned by the MPRIS provider boundary."""

    @property
    def connected(self) -> bool: ...

    async def connect(self) -> None: ...

    def close(self) -> None: ...

    async def player_names(self) -> list[str]: ...

    async def player(self, name: str, /) -> MprisPlayerPort | None: ...

    async def status(self, player: MprisPlayerPort, /) -> str: ...

    async def track(self, player: MprisPlayerPort, /) -> TrackInfo | None: ...

    async def position(self, player: MprisPlayerPort, /) -> float | None: ...

    async def identity(self) -> str: ...

    async def describe(self, name: str, /) -> tuple[str, str, TrackInfo]: ...

    async def subscribe(
        self,
        name: str,
        callback: Callable[[MprisPropertyChange], None],
        /,
    ) -> None: ...


@dataclass(frozen=True)
class PlaybackSample:
    """One normalized MPRIS sample plus the metadata needed by lyric policy."""

    observation: PlaybackObservation
    info: TrackInfo
    transitioning: bool
    commit: TrackCommit | None


PlaybackListener = Callable[[PlaybackSample], None]
CommitListener = Callable[[TrackCommit], None]
NoPlayerListener = Callable[[float], None]


class MprisPlaybackCoordinator:
    """Own the complete MPRIS session and emit stable playback facts."""

    def __init__(
        self,
        *,
        poll_interval: float = 0.2,
        session: MprisSessionPort,
        playback_adapter: MprisPlaybackAdapter,
        on_sample: PlaybackListener | None = None,
        on_commit: CommitListener | None = None,
        on_no_player: NoPlayerListener | None = None,
    ) -> None:
        if poll_interval <= 0.0:
            raise ValueError("MPRIS poll interval must be positive")
        self._poll_interval = poll_interval
        self._session = session
        self._playback_adapter = playback_adapter
        self._on_sample = on_sample
        self._on_commit = on_commit
        self._on_no_player = on_no_player
        self._task: asyncio.Task[None] | None = None
        self._poll_wakeup = asyncio.Event()
        self._selector = PlayerSelector()
        self._stabilizer = TrackStabilizer()
        self._current_commit: TrackCommit | None = None
        self._last_raw_position: float | None = None
        self._subscribed_name: str | None = None
        self._last_logged_playback_state: tuple[str, str] | None = None

    @property
    def current_commit(self) -> TrackCommit | None:
        """Return the latest stabilized track commit, if any."""
        return self._current_commit

    @property
    def last_raw_position(self) -> float | None:
        """Return the latest raw player position for cumulative-timeline policy."""
        return self._last_raw_position

    @property
    def transitioning(self) -> bool:
        """Whether metadata is still settling after a player transition."""
        return self._stabilizer.transitioning

    @property
    def player_lock(self) -> str:
        """Return the configured MPRIS bus-name lock."""
        return self._selector.lock

    @property
    def current_player_name(self) -> str | None:
        """Return the player selected by the latest poll, if one is active."""
        return self._selector.current_name

    @property
    def session(self) -> MprisSessionPort:
        """Expose the owned session for read-only diagnostics and tests."""
        return self._session

    def set_player_lock(self, bus_name: str) -> None:
        """Change the preferred player and wake the poller immediately."""
        updated = bus_name if isinstance(bus_name, str) else ""
        if updated == self._selector.lock:
            return
        self._selector.lock = updated
        self._poll_wakeup.set()

    async def available_players(self) -> list[PlayerInfo]:
        """Describe reachable MPRIS players for the settings UI."""
        if not self._session.connected:
            return []
        result: list[PlayerInfo] = []
        records: list[PlayerRecord] = []
        for name in await self._session.player_names():
            try:
                identity, status, info = await self._session.describe(name)
            except LookupError:
                continue
            records.append(PlayerRecord(None, name, status, info))
            result.append(PlayerInfo(name, identity, info.title, info.artist, status))
        automatic_name = self._selector.automatic_name(records)
        return [
            PlayerInfo(p.bus_name, p.identity, p.title, p.artist, p.playback_status, p.bus_name == automatic_name)
            for p in result
        ]

    async def start(self) -> None:
        """Connect the session and start the owned poll task."""
        task = self._task
        if task is not None:
            if not task.done():
                return
            self._task = None
        self.reset()
        try:
            await self._session.connect()
            task = create_owned_task(self._run(), name="kotonoha-mpris-playback")
        except asyncio.CancelledError:
            self._close_failed_start_session()
            raise
        except (MprisSessionError, OSError, TimeoutError, RuntimeError, TypeError, ValueError):
            self._close_failed_start_session()
            raise
        self._task = task
        task.add_done_callback(self._playback_task_finished)

    def _close_failed_start_session(self) -> None:
        """Release a session acquired by a failed playback startup."""
        try:
            self._session.close()
        except (MprisSessionError, OSError, TimeoutError, RuntimeError, ValueError) as exc:
            logger.warning("Could not close MPRIS session after startup failure: %s", exc)

    def _playback_task_finished(self, task: asyncio.Task[None]) -> None:
        """Observe unexpected poll-task failures when no later stop occurs."""
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error("MPRIS playback task failed: %s", error)

    async def stop(self) -> None:
        """Cancel polling, close the session, and reset restartable state."""
        task = self._task
        self._task = None
        cancellation_requested = False
        try:
            if task is not None:
                if not task.done():
                    task.cancel()
                cancellation_requested = await wait_for_owned(task)
        finally:
            self._subscribed_name = None
            try:
                self._session.close()
            finally:
                self.reset()
        if cancellation_requested:
            raise asyncio.CancelledError

    async def poll_once(self, *, now: float | None = None) -> None:
        """Sample the selected player once; exposed for deterministic tests."""
        observed_at = time.monotonic() if now is None else now
        active = await self._active_player(now=observed_at)
        if active is None:
            self._subscribed_name = None
            self._notify_no_player(observed_at)
            return

        player, name = active
        if self._subscribed_name != name:
            await self._session.subscribe(name, self._on_properties_changed)
            self._subscribed_name = name
        status = await self._session.status(player)
        if status not in {"Playing", "Paused"}:
            self._subscribed_name = None
            self._notify_no_player(observed_at)
            return

        identity = await self._session.identity()
        first_info = await self._session.track(player)
        if first_info is None:
            logger.debug("metadata sample was unavailable")
            return

        position = await self._session.position(player)
        if position is not None:
            self._last_raw_position = position

        second_info = await self._session.track(player)
        if second_info is None:
            logger.debug("metadata verification was unavailable")
            return
        if first_info.identity_key != second_info.identity_key:
            self._stabilizer.observe(
                TrackObservation(name, TrackInfo("", "", "", None, ""), status, position, observed_at)
            )
            self._poll_wakeup.set()
            return

        info = second_info
        playback_state = (name, status)
        if self._last_logged_playback_state is not None and playback_state != self._last_logged_playback_state:
            logger.info(
                "MPRIS playback state changed: player=%r status=%s track=%r / %r position=%s",
                name,
                status,
                info.title,
                info.artist,
                _position_text(position),
            )
        self._last_logged_playback_state = playback_state
        track_observation = TrackObservation(name, info, status, position, observed_at, identity)
        commit = self._stabilizer.observe(track_observation)
        if not info.title and not info.artist:
            return

        observation = self._playback_adapter.observe(
            info,
            player_name=name,
            status=status,
            position_s=position,
            observed_at=observed_at,
        )
        if commit is not None:
            self._current_commit = commit
            logger.info(
                "MPRIS track committed: generation=%d player=%r track=%r / %r id=%r "
                "status=%s raw_position=%s start_position=%s",
                commit.generation,
                commit.player_name,
                commit.info.title,
                commit.info.artist,
                commit.info.track_id,
                status,
                _position_text(position),
                _position_text(commit.start_position),
            )
            if self._on_commit is not None:
                self._on_commit(commit)
        sample = PlaybackSample(observation, info, self._stabilizer.transitioning, commit)
        if self._on_sample is not None:
            self._on_sample(sample)

    async def _run(self) -> None:
        try:
            while True:
                self._poll_wakeup.clear()
                try:
                    await self.poll_once()
                except asyncio.CancelledError:
                    raise
                except (MprisSessionError, OSError, TimeoutError, ValueError) as exc:
                    logger.debug("MPRIS poll error: %s", exc)
                try:
                    await asyncio.wait_for(self._poll_wakeup.wait(), timeout=self._poll_interval)
                except TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise

    async def _active_player(self, *, now: float) -> tuple[MprisPlayerPort, str] | None:
        names = await self._session.player_names()
        self._selector.forget_absent(set(names))
        ordered = self._selector.order_to_poll(names)

        collected: list[PlayerRecord] = []
        for name in ordered:
            player = await self._session.player(name)
            if player is None:
                self._selector.observe(name, "", now)
                continue
            status = await self._session.status(player)
            self._selector.observe(name, status, now)
            if status not in {"Playing", "Paused"}:
                continue
            info = await self._session.track(player)
            if info is None and name != self._selector.lock:
                continue
            if info is None:
                info = TrackInfo("", "", "", None, "")
            collected.append(PlayerRecord(player, name, status, info))

        selected = self._selector.choose(collected)
        previous_name = self._selector.current_name
        if selected is None or selected.player is None:
            self._selector.current_name = None
            if previous_name is not None:
                logger.info(
                    "MPRIS player selection cleared: previous=%r reason=no followable player",
                    previous_name,
                )
            return None
        self._selector.current_name = selected.bus_name
        if selected.bus_name != previous_name:
            logger.info(
                "MPRIS player selected: bus=%r status=%s track=%r / %r id=%r",
                selected.bus_name,
                selected.status,
                selected.info.title,
                selected.info.artist,
                selected.info.track_id,
            )
        return selected.player, selected.bus_name

    def _on_properties_changed(self, change: MprisPropertyChange) -> None:
        if change.interface != MPRIS_PLAYER_IFACE:
            return
        if {"Metadata", "PlaybackStatus"}.intersection(change.changed) or {
            "Metadata",
            "PlaybackStatus",
        }.intersection(change.invalidated):
            self._poll_wakeup.set()

    def _notify_no_player(self, observed_at: float) -> None:
        if self._on_no_player is not None:
            self._on_no_player(observed_at)

    def reset(self) -> None:
        """Forget playback history so a later start observes the current player anew."""
        self._stabilizer.reset()
        self._selector.reset()
        self._current_commit = None
        self._last_raw_position = None
        self._subscribed_name = None
        self._last_logged_playback_state = None


def _position_text(position: float | None) -> str:
    """Format optional playback positions consistently in operational logs."""
    return "-" if position is None else f"{position:.3f}s"


__all__ = ["MprisPlaybackCoordinator", "MprisSessionPort", "PlaybackSample"]
