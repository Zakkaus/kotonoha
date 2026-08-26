"""Secure persistence boundary for the optional Cider API token."""

from __future__ import annotations

import logging
from typing import Protocol

import keyring
import keyring.errors

logger = logging.getLogger(__name__)

CIDER_KEYRING_SERVICE = "dev.locez.kotonoha"
CIDER_KEYRING_ACCOUNT = "cider-api-token"


class CiderApiTokenStore(Protocol):
    """Synchronous credential-store contract used behind an owned worker."""

    def load(self) -> str:
        """Return the stored token, or an empty string when none is available."""
        ...

    def save(self, token: str) -> None:
        """Store or clear the token without exposing it to callers or logs."""
        ...


class KeyringCiderApiTokenStore:
    """Read and write the Cider token through the user's OS keyring."""

    def load(self) -> str:
        """Load a token from the configured Secret Service/KWallet backend."""
        try:
            token = keyring.get_password(CIDER_KEYRING_SERVICE, CIDER_KEYRING_ACCOUNT)
        except keyring.errors.KeyringError as exc:
            logger.warning("Could not read the Cider API token from the system keyring: %s", exc)
            return ""
        return token.strip() if token is not None and token.strip() else ""

    def save(self, token: str) -> None:
        """Store a non-empty token or remove the existing credential."""
        normalized = token.strip()
        try:
            if normalized:
                keyring.set_password(CIDER_KEYRING_SERVICE, CIDER_KEYRING_ACCOUNT, normalized)
                return
            existing = keyring.get_password(CIDER_KEYRING_SERVICE, CIDER_KEYRING_ACCOUNT)
            if existing is not None:
                keyring.delete_password(CIDER_KEYRING_SERVICE, CIDER_KEYRING_ACCOUNT)
        except keyring.errors.KeyringError as exc:
            logger.warning("Could not save the Cider API token to the system keyring: %s", exc)


__all__ = [
    "CIDER_KEYRING_ACCOUNT",
    "CIDER_KEYRING_SERVICE",
    "CiderApiTokenStore",
    "KeyringCiderApiTokenStore",
]
