"""Application configuration loaded from environment variables via Pydantic Settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BASE_DIR / ".env", BASE_DIR.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- Database ----
    database_url: str = "postgresql+asyncpg://admin:admin@localhost:5432/hrservice"

    # ---- Security ----
    encryption_key: str = "change-me-to-a-random-32-byte-hex-string-in-production"
    secret_key: str = "change-me-to-a-random-secret-key"
    session_lifetime_days: int = 7
    bcrypt_rounds: int = 12
    is_production: bool = False

    # ---- Data TTL ----
    search_ttl_days: int = 7
    candidate_view_ttl_days: int = 30
    cleanup_interval_hours: int = 6

    # ---- HH API ----
    hh_api_url: str = "https://api.hh.ru/resumes"
    hh_host: str = "rabota.by"

    # ---- HH OAuth ----
    hh_app_client_id: str = ""
    hh_app_client_secret: str = ""
    hh_app_token: str = ""
    hh_user_agent: str = ""
    hh_redirect_uri: str = ""

    # ---- OpenAI / LLM ----
    openai_api_key: str = ""
    openai_api_base: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    llm_max_concurrent: int = 5
    evaluation_temperature: float = 0.1

    # ---- Frontend (CORS) ----
    frontend_origin: str = "http://localhost:3000"


settings = Settings()
