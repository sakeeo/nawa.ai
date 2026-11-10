from functools import lru_cache

from pydantic import Field, SecretStr
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
    demo_database_name: str = "noesantara"

    jwt_secret: str = Field(min_length=32)
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 604_800
    invite_ttl_seconds: int = 604_800
    login_limit_per_email: int = 5
    login_limit_per_ip: int = 20
    login_window_seconds: int = 300

    deepseek_api_key: str = ""
    llm_model: str = "deepseek/deepseek-chat"
    llm_fallback_model: str = ""
    ollama_chat_model: str = "qwen2.5:7b"
    ollama_api_base: str = "http://ollama:11434"
    embedding_model: str = "ollama/bge-m3"

    upload_dir: str = "/data/uploads"
    max_upload_bytes: int = 20 * 1024 * 1024
    max_pdf_pages: int = 200

    rag_vector_k: int = 30
    rag_keyword_k: int = 30
    rag_rrf_k: int = 60
    rag_final_k: int = 20
    rag_rerank_top_n: int = 20
    rag_context_k: int = 5
    rag_min_similarity: float = 0.60
    rag_context_max_tokens: int = 3000
    chat_limit_per_minute: int = 20
    reranker_enabled: bool = False
    reranker_url: str = ""
    reranker_timeout_seconds: float = 10.0

    data_encryption_key: str | None = None
    data_query_timeout_s: int = 10
    data_max_rows: int = 1000
    data_link_top_tables: int = 4
    demo_db_readonly_user: str = "nawa_demo_ro"
    demo_db_readonly_password: str | None = None

    langfuse_host: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr | None = None

    @property
    def local_llm_model(self) -> str:
        return f"ollama/{self.ollama_chat_model}"

    @property
    def cookie_secure(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
