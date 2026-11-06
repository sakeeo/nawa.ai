import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from nawa.core.errors import AuthenticationError
from nawa.core.security import (
    DUMMY_HASH,
    create_access_token,
    decode_access_token,
    hash_password,
    hash_token,
    new_token,
    verify_password,
)

SECRET = "x" * 40


def test_password_roundtrip() -> None:
    hashed = hash_password("correct horse battery")
    assert hashed != "correct horse battery"
    assert verify_password(hashed, "correct horse battery") is True
    assert verify_password(hashed, "wrong") is False


def test_password_hash_is_salted() -> None:
    assert hash_password("same") != hash_password("same")


def test_verify_password_rejects_garbage_hash() -> None:
    assert verify_password("not-a-hash", "anything") is False


def test_dummy_hash_never_verifies() -> None:
    assert verify_password(DUMMY_HASH, "anything") is False


def test_tokens_are_unique_and_hash_is_stable() -> None:
    first, second = new_token(), new_token()
    assert first != second
    assert len(first) >= 40
    assert hash_token(first) == hash_token(first)
    assert hash_token(first) != first
    assert len(hash_token(first)) == 64


def test_access_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(user_id=user_id, secret=SECRET, ttl_seconds=60)
    assert decode_access_token(token, secret=SECRET) == user_id


def test_expired_access_token_is_rejected() -> None:
    past = datetime.now(UTC) - timedelta(hours=1)
    token = create_access_token(user_id=uuid.uuid4(), secret=SECRET, ttl_seconds=60, now=past)
    with pytest.raises(AuthenticationError):
        decode_access_token(token, secret=SECRET)


def test_wrong_secret_is_rejected() -> None:
    token = create_access_token(user_id=uuid.uuid4(), secret=SECRET, ttl_seconds=60)
    with pytest.raises(AuthenticationError):
        decode_access_token(token, secret="y" * 40)


def test_wrong_token_type_is_rejected() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "refresh", "exp": now + timedelta(minutes=5)},
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(AuthenticationError):
        decode_access_token(token, secret=SECRET)


def test_unsigned_token_is_rejected() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "exp": now + timedelta(minutes=5)},
        key="",
        algorithm="none",
    )
    with pytest.raises(AuthenticationError):
        decode_access_token(token, secret=SECRET)


def test_garbage_token_is_rejected() -> None:
    with pytest.raises(AuthenticationError):
        decode_access_token("garbage", secret=SECRET)
