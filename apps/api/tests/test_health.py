import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from nawa.core.config import get_settings
from nawa.core.health import ReadinessCheck, get_readiness_checks
from nawa.main import create_app


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("REDIS_URL", "redis://h:6379/0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def client_with(checks: dict[str, ReadinessCheck]) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_readiness_checks] = lambda: checks
    return TestClient(app)


async def ok() -> None:
    return None


async def fail() -> None:
    raise ConnectionError("down")


def test_healthz_is_ok_without_dependencies() -> None:
    response = client_with({"postgres": fail}).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_ready_when_all_checks_pass() -> None:
    response = client_with({"postgres": ok, "redis": ok}).get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"postgres": "ok", "redis": "ok"}}


def test_readyz_503_when_a_check_fails() -> None:
    response = client_with({"postgres": ok, "redis": fail}).get("/readyz")
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"postgres": "ok", "redis": "failed"},
    }


def test_readyz_logs_failure_without_leaking_it(caplog: pytest.LogCaptureFixture) -> None:
    client = client_with({"redis": fail})
    # create_app() reconfigures root logging and drops caplog's handler; re-attach it.
    logging.getLogger().addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger="nawa.health"):
            response = client.get("/readyz")
    finally:
        logging.getLogger().removeHandler(caplog.handler)
    records = [r for r in caplog.records if r.name == "nawa.health"]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].getMessage() == "readiness check failed"
    assert records[0].exc_info is not None
    assert "down" not in response.text
