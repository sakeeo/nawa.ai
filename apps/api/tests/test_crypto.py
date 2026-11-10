import pytest
from cryptography.fernet import Fernet

from nawa.core.crypto import CredentialVault
from nawa.core.errors import ServiceUnavailableError


def _key() -> str:
    return Fernet.generate_key().decode()


def test_round_trip() -> None:
    vault = CredentialVault(_key())
    assert vault.decrypt(vault.encrypt("s3cret-päss")) == "s3cret-päss"


def test_ciphertext_differs_per_call_and_hides_plaintext() -> None:
    vault = CredentialVault(_key())
    first, second = vault.encrypt("hunter2-password"), vault.encrypt("hunter2-password")
    assert first != second
    assert "hunter2" not in first


def test_wrong_key_cannot_decrypt() -> None:
    token = CredentialVault(_key()).encrypt("secret")
    with pytest.raises(ValueError):
        CredentialVault(_key()).decrypt(token)


def test_tampered_token_is_rejected() -> None:
    vault = CredentialVault(_key())
    token = vault.encrypt("secret")
    tampered = token[:-4] + ("AAAA" if token[-4:] != "AAAA" else "BBBB")
    with pytest.raises(ValueError):
        vault.decrypt(tampered)


@pytest.mark.parametrize("key", [None, "", "not-a-fernet-key"])
def test_missing_or_malformed_key_is_service_unavailable(key: str | None) -> None:
    vault = CredentialVault(key)
    with pytest.raises(ServiceUnavailableError):
        vault.encrypt("x")
    with pytest.raises(ServiceUnavailableError):
        vault.decrypt("x")


def test_error_message_does_not_leak_the_key() -> None:
    with pytest.raises(ServiceUnavailableError) as info:
        CredentialVault("not-a-fernet-key").encrypt("x")
    assert "not-a-fernet-key" not in str(info.value)
    assert "DATA_ENCRYPTION_KEY" in str(info.value)
