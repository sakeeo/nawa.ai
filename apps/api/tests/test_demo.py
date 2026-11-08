import logging

import pytest
from noesantara_seed import load as seed_load

from nawa.core.config import Settings
from nawa.workspace.demo import demo_database_urls, load_demo_data

BASE = {"database_url": "x", "redis_url": "x", "jwt_secret": "s" * 32}
OWNER = "postgresql+asyncpg://owner:pw@postgres:5432/nawa"


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})  # type: ignore[arg-type]


def test_urls_swap_only_the_database_name() -> None:
    admin, target = demo_database_urls(OWNER, "noesantara")
    assert admin == "postgresql+asyncpg://owner:pw@postgres:5432/postgres"
    assert target == "postgresql+asyncpg://owner:pw@postgres:5432/noesantara"


async def test_skipped_without_owner_url(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="nawa.demo"):
        assert await load_demo_data(_settings()) is False
    assert "DATABASE_OWNER_URL" in caplog.text


async def test_creates_database_then_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    async def fake_ensure(admin_url: str, name: str) -> None:
        calls.append(("ensure", name))

    async def fake_load(url: str, seed: int = 42) -> dict[str, int]:
        calls.append(("load", url))
        return {"orders": 1}

    monkeypatch.setattr(seed_load, "ensure_database", fake_ensure)
    monkeypatch.setattr(seed_load, "load_async", fake_load)
    assert await load_demo_data(_settings(database_owner_url=OWNER)) is True
    assert calls == [("ensure", "noesantara"), ("load", OWNER.rsplit("/", 1)[0] + "/noesantara")]


async def test_failure_is_logged_not_raised(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def boom(admin_url: str, name: str) -> None:
        raise OSError("db down")

    monkeypatch.setattr(seed_load, "ensure_database", boom)
    with caplog.at_level(logging.ERROR, logger="nawa.demo"):
        assert await load_demo_data(_settings(database_owner_url=OWNER)) is False
    assert "Demo data load failed" in caplog.text


def test_database_name_is_validated() -> None:
    with pytest.raises(ValueError, match="database name"):
        seed_load.validate_database_name('x"; DROP DATABASE nawa; --')
