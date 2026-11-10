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


def test_data_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("REDIS_URL", "redis://h:6379/0")
    for name in ("DATA_ENCRYPTION_KEY", "DEMO_DB_READONLY_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert settings.data_encryption_key is None
    assert settings.data_query_timeout_s == 10
    assert settings.data_max_rows == 1000
    assert settings.data_link_top_tables == 4
    assert settings.demo_db_readonly_user == "nawa_demo_ro"
    assert settings.demo_db_readonly_password is None
    assert settings.data_ask_limit_per_minute == 20


def test_knowledge_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("REDIS_URL", "redis://h:6379/0")
    settings = Settings(_env_file=None)
    assert settings.upload_dir == "/data/uploads"
    assert settings.max_upload_bytes == 20 * 1024 * 1024
    assert settings.max_pdf_pages == 200
