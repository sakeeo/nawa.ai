import pytest

from nawa.core.config import Settings, get_settings


def test_settings_read_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("REDIS_URL", "redis://h:6379/0")
    monkeypatch.setenv("OFFLINE_MODE", "true")
    settings = Settings(_env_file=None)
    assert settings.database_url == "postgresql+asyncpg://u:p@h/db"
    assert settings.redis_url == "redis://h:6379/0"
    assert settings.offline_mode is True
    assert settings.environment == "development"
    assert settings.log_level == "INFO"


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://h:6379/0")
    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("REDIS_URL", "redis://h:6379/0")
    get_settings.cache_clear()
    assert get_settings() is get_settings()
    get_settings.cache_clear()


def test_jwt_secret_is_required_and_must_be_long(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("REDIS_URL", "redis://h:6379/0")
    monkeypatch.setenv("JWT_SECRET", "short")
    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_auth_defaults_and_cookie_secure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("REDIS_URL", "redis://h:6379/0")
    monkeypatch.setenv("JWT_SECRET", "s" * 40)
    settings = Settings(_env_file=None)
    assert settings.access_token_ttl_seconds == 900
    assert settings.refresh_token_ttl_seconds == 604_800
    assert settings.cookie_secure is False
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert Settings(_env_file=None).cookie_secure is True
