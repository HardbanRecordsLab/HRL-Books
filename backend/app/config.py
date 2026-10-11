"""Settings from environment. No fallback secrets: the app refuses to start without them (spec 9.1)."""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Explicit driver in the URL (postgresql+psycopg2://…) — see handbook R-18.
    DATABASE_URL: str
    JWT_SECRET: str
    ACCESS_TOKEN_MINUTES: int = 15
    REFRESH_TOKEN_DAYS: int = 30
    INVITATION_DAYS: int = 7
    PUBLIC_REGISTRATION: bool = False  # FR-ACC-01: invitation-only by default
    LOGIN_MAX_FAILURES: int = 5
    LOGIN_LOCK_MINUTES: int = 15
    APP_URL: str = "https://hrl-books.hardbanrecordslab.online"

    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SENDER_EMAIL: str = "no-reply@hardbanrecordslab.online"

    FILES_DIR: str = "/app/data/files"
    MAX_UPLOAD_MB: int = 45
    GELATO_API_KEY: str | None = None
    STRIPE_SECRET_KEY: str | None = None
    STRIPE_WEBHOOK_SECRET: str | None = None
    OPENROUTER_API_KEY: str | None = None
    LLM_BASE_URL: str = "https://openrouter.ai/api/v1"
    LLM_MODEL: str = "deepseek/deepseek-chat-v3-0324"
    LLM_MODEL_FALLBACK: str = "meta-llama/llama-3.3-70b-instruct"
    LLM_TIMEOUT: int = 180
    SHOP_COUNTRIES: str = "PL,DE,CZ,SK,LT,AT,NL,BE,FR,IT,ES,IE,DK,SE,FI,PT,GB,US"

    @field_validator("JWT_SECRET")
    @classmethod
    def _strong_secret(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
