import keyring

from kotonoha.providers.cider_credentials import (
    CIDER_KEYRING_ACCOUNT,
    CIDER_KEYRING_SERVICE,
    KeyringCiderApiTokenStore,
)


def test_keyring_store_normalizes_and_clears_tokens(monkeypatch):
    stored: str | None = None

    def get_password(service: str, account: str) -> str | None:
        assert service == CIDER_KEYRING_SERVICE
        assert account == CIDER_KEYRING_ACCOUNT
        return stored

    def set_password(service: str, account: str, password: str) -> None:
        nonlocal stored
        assert service == CIDER_KEYRING_SERVICE
        assert account == CIDER_KEYRING_ACCOUNT
        stored = password

    def delete_password(service: str, account: str) -> None:
        nonlocal stored
        assert service == CIDER_KEYRING_SERVICE
        assert account == CIDER_KEYRING_ACCOUNT
        stored = None

    monkeypatch.setattr(keyring, "get_password", get_password)
    monkeypatch.setattr(keyring, "set_password", set_password)
    monkeypatch.setattr(keyring, "delete_password", delete_password)

    store = KeyringCiderApiTokenStore()
    assert store.load() == ""

    store.save("  test-token  ")
    assert store.load() == "test-token"

    store.save("  ")
    assert store.load() == ""
