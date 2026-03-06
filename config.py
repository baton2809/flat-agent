"""Application configuration with validation."""

from functools import lru_cache
from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    gigachat_credentials: str
    gigachat_scope: str = "GIGACHAT_API_B2B"
    gigachat_model: str = "GigaChat"
    gigachat_verify_ssl: bool = True

    telegram_bot_token: str
    telegram_webhook_secret: str = ""

    webhook_url: str = ""
    host: str = "0.0.0.0"
    port: int = 8000

    db_path: Path = Path("checkpoints.db")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @field_validator("gigachat_credentials")
    @classmethod
    def credentials_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("GIGACHAT_CREDENTIALS is required")
        return v

    @field_validator("telegram_bot_token")
    @classmethod
    def token_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


_llm_instance = None


def get_llm():
    """Return singleton LLM instance (initialised on first call)."""
    global _llm_instance
    if _llm_instance is None:
        from agent.llm_wrapper import GigaChatWrapper
        s = get_settings()
        _llm_instance = GigaChatWrapper(
            credentials=s.gigachat_credentials,
            scope=s.gigachat_scope,
            model=s.gigachat_model,
            verify_ssl_certs=s.gigachat_verify_ssl,
            temperature=0.7,
        )
    return _llm_instance
