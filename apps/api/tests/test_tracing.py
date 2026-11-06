import os
from collections.abc import Iterator

import litellm
import pytest
from pydantic import SecretStr

from nawa.core.config import Settings
from nawa.intelligence.tracing import configure_litellm

BASE = {"database_url": "x", "redis_url": "x", "jwt_secret": "s" * 32}
LANGFUSE_VARS = ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")


@pytest.fixture(autouse=True)
def clean_langfuse_env() -> Iterator[None]:
    """configure_litellm exports LANGFUSE_* to os.environ; keep tests independent."""
    for name in LANGFUSE_VARS:
        os.environ.pop(name, None)
    yield
    for name in LANGFUSE_VARS:
        os.environ.pop(name, None)
    litellm.success_callback = []
    litellm.failure_callback = []


def test_langfuse_callbacks_enabled_with_keys() -> None:
    configure_litellm(
        Settings(
            _env_file=None,
            **BASE,
            langfuse_host="http://langfuse:3000",
            langfuse_public_key="pk-lf-x",
            langfuse_secret_key=SecretStr("sk-lf-x"),
        )
    )
    assert litellm.success_callback == ["langfuse"]
    assert litellm.failure_callback == ["langfuse"]


def test_no_callbacks_without_keys() -> None:
    configure_litellm(Settings(_env_file=None, **BASE))
    assert litellm.success_callback == []
    assert litellm.failure_callback == []
