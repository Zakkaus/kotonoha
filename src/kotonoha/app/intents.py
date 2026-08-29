"""Typed commands crossing from presentation into application workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from ..config import Config
from ..config.schema import SETTINGS_CONFIG_FIELDS
from ..lyrics.cache import LyricsCacheKey, LyricsCacheQuery


@dataclass(frozen=True, slots=True)
class ApplyConfig:
    """Apply a complete form value set and its effective user changes.

    The complete ``Config`` keeps the intent easy to inspect. ``changed_fields``
    lets the application merge the form with newer runtime-owned values when the
    dialog stayed open.
    """

    config: Config
    changed_fields: frozenset[str] = frozenset(SETTINGS_CONFIG_FIELDS)


@dataclass(frozen=True, slots=True)
class ClearCache:
    """Remove persisted lyrics cache entries."""


@dataclass(frozen=True, slots=True)
class OpenCacheManagement:
    """Open the separate local lyrics cache management window."""


@dataclass(frozen=True, slots=True)
class SearchCache:
    """Search cache metadata using the query entered by the user."""

    query: LyricsCacheQuery


@dataclass(frozen=True, slots=True)
class DeleteCacheEntries:
    """Delete the exact cache rows selected in the management window."""

    keys: tuple[LyricsCacheKey, ...]


@dataclass(frozen=True, slots=True)
class RequestRestart:
    """Restart the process after settings that require it are applied."""


@dataclass(frozen=True, slots=True)
class ChangeTrackOffset:
    """Persist one output timing correction for a normalized track key."""

    key: str
    offset_ms: int


@dataclass(frozen=True, slots=True)
class ChangePosition:
    """Persist a platform-accepted output-local overlay placement."""

    margin_edge: int
    margin_x: int
    screen_name: str
    screen_width: int
    screen_height: int


SettingsIntent: TypeAlias = (
    ApplyConfig
    | ClearCache
    | OpenCacheManagement
    | SearchCache
    | DeleteCacheEntries
    | RequestRestart
    | ChangeTrackOffset
    | ChangePosition
)

__all__ = [
    "ApplyConfig",
    "ChangePosition",
    "ChangeTrackOffset",
    "ClearCache",
    "DeleteCacheEntries",
    "OpenCacheManagement",
    "RequestRestart",
    "SearchCache",
    "SettingsIntent",
]
