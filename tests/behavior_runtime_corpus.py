"""Typed public behavior cases for runtime coordination boundaries."""

from __future__ import annotations

from dataclasses import dataclass

from behavior_corpus import BehaviorCase, RegressionSource

from kotonoha.lyrics.match import TrackMetadata
from kotonoha.model import LyricsSnapshot


@dataclass(frozen=True)
class GateSnapshotInput:
    """One Cider snapshot observation crossing the gate boundary."""

    client_id: int
    snapshot: LyricsSnapshot


@dataclass(frozen=True)
class GateTickInput:
    """One Cider timing observation tied to the latest snapshot."""

    client_id: int
    current_time: float | None
    is_playing: bool | None


GateEvent = GateSnapshotInput | GateTickInput


@dataclass(frozen=True)
class GateInput:
    """Ordered Cider events and the current player identity."""

    track: TrackMetadata
    events: tuple[GateEvent, ...]
    mode: str


@dataclass(frozen=True)
class GateOutput:
    """Canonical source-gate facts used by lyrics workflow policy."""

    match_client_id: int | None
    match_confidence: str | None
    timing_client_id: int | None
    timing_current_time: float | None
    accept_ws: bool


GATE_CASES: tuple[BehaviorCase[GateInput, GateOutput], ...] = (
    BehaviorCase(
        case_id="gate.external-lyrics-cider-clock",
        input=GateInput(
            TrackMetadata("Song", "Artist"),
            (
                GateSnapshotInput(
                    10,
                    LyricsSnapshot(found=False, title="Song", artist="Artist", duration_s=194.222),
                ),
                GateTickInput(10, 12.5, True),
            ),
            "external",
        ),
        expected=GateOutput(None, None, 10, 12.5, False),
        negative_variants=(
            GateInput(
                TrackMetadata("Other", "Artist"),
                (
                    GateSnapshotInput(
                        10,
                        LyricsSnapshot(found=False, title="Song", artist="Artist", duration_s=194.222),
                    ),
                    GateTickInput(10, 12.5, True),
                ),
                "external",
            ),
        ),
        source=RegressionSource(
            "#59/#63", "a matching Cider tick can calibrate external lyrics without publishing Cider content"
        ),
        rule_ids=("gate.external_mode", "gate.tick_track_match", "gate.ws_ownership"),
    ),
    BehaviorCase(
        case_id="gate.stale-tick-generation",
        input=GateInput(
            TrackMetadata("Song", "Artist"),
            (
                GateSnapshotInput(
                    10,
                    LyricsSnapshot(found=False, title="Song", artist="Artist"),
                ),
                GateTickInput(10, 12.5, True),
                GateSnapshotInput(
                    10,
                    LyricsSnapshot(found=False, title="Song", artist="Artist"),
                ),
            ),
            "external",
        ),
        expected=GateOutput(None, None, None, None, False),
        negative_variants=(
            GateInput(
                TrackMetadata("Song", "Artist"),
                (
                    GateSnapshotInput(
                        10,
                        LyricsSnapshot(found=False, title="Song", artist="Artist"),
                    ),
                    GateTickInput(10, 12.5, True),
                ),
                "external",
            ),
        ),
        source=RegressionSource("#63", "a tick tied to an older snapshot generation is discarded"),
        rule_ids=("gate.tick_generation",),
    ),
)


@dataclass(frozen=True)
class ClockSyncInput:
    """One clock sample and the monotonic time since the previous sample."""

    media_time: float | None
    playing: bool
    wall_delta: float


@dataclass(frozen=True)
class ClockInput:
    """A deterministic sequence of media clock observations."""

    syncs: tuple[ClockSyncInput, ...]


@dataclass(frozen=True)
class ClockOutput:
    """Canonical clock observation exposed to timeline policy."""

    media_time: float | None
    playing: bool


CLOCK_CASES: tuple[BehaviorCase[ClockInput, ClockOutput], ...] = (
    BehaviorCase(
        case_id="clock.missing-position-is-noop",
        input=ClockInput(
            (
                ClockSyncInput(10.0, False, 0.0),
                ClockSyncInput(11.0, False, 1.0),
                ClockSyncInput(None, False, 0.0),
                ClockSyncInput(None, False, 1.0),
            )
        ),
        expected=ClockOutput(12.0, True),
        negative_variants=(ClockInput((ClockSyncInput(None, False, 0.0),)),),
        source=RegressionSource("#59", "an unavailable Position does not erase the last valid clock anchor"),
        rule_ids=("clock.position_unavailable", "clock.pause_resume"),
    ),
)


@dataclass(frozen=True)
class PlatformOperationInput:
    """The public operation outcome a platform adapter reports."""

    succeeded: bool
    reason: str | None = None


@dataclass(frozen=True)
class PlatformOperationOutput:
    """Canonical operation result consumed by application policy."""

    succeeded: bool
    reason: str | None


PLATFORM_CASES: tuple[BehaviorCase[PlatformOperationInput, PlatformOperationOutput], ...] = (
    BehaviorCase(
        case_id="platform.operation-failure-reason",
        input=PlatformOperationInput(False, "output disappeared"),
        expected=PlatformOperationOutput(False, "output disappeared"),
        negative_variants=(PlatformOperationInput(True),),
        source=RegressionSource(
            "#27/#30", "a platform failure must carry a reason instead of becoming a no-op success"
        ),
        rule_ids=("platform.operation_result", "platform.failure_reason"),
    ),
)


__all__ = [
    "CLOCK_CASES",
    "ClockInput",
    "ClockOutput",
    "ClockSyncInput",
    "GATE_CASES",
    "GateEvent",
    "GateInput",
    "GateOutput",
    "GateSnapshotInput",
    "GateTickInput",
    "PLATFORM_CASES",
    "PlatformOperationInput",
    "PlatformOperationOutput",
]
