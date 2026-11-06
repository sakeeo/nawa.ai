from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Secrets come from the environment only."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"
    offline_mode: bool = False
    database_url: str
    database_owner_url: str | None = None
    redis_url: str

    jwt_secret: str = Field(min_length=32)
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 604_800
    invite_ttl_seconds: int = 604_800
    login_limit_per_email: int = 5
    login_limit_per_ip: int = 20
    login_window_seconds: int = 300

    deepseek_api_key: str = ""

    @property
    def cookie_secure(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
