from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or a local .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SAMIDA_",
        extra="ignore",
    )

    app_name: str = "SAMIDA"
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "gemma4:e4b"
    ollama_vision_model: str = "qwen3-vl:8b"
    openai_api_key: str | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
    )
    openai_model: str = "gpt-5.6-luna"
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias="ANTHROPIC_API_KEY",
    )
    anthropic_model: str = "claude-opus-5"
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    cors_extra_origins: str = ""
    request_timeout_seconds: float = Field(default=120.0, gt=0)
    camofox_enabled: bool = True
    camofox_base_url: str = "http://127.0.0.1:9377"
    project_root: Path = Path(__file__).resolve().parents[2]
    database_path: Path | None = None
    attachments_dir: Path | None = None
    logs_dir: Path | None = None

    def resolved_database_path(self) -> Path:
        return self.database_path or self.project_root / "data" / "samida.db"

    def resolved_attachments_dir(self) -> Path:
        return self.attachments_dir or self.project_root / "data" / "attachments"

    def resolved_logs_dir(self) -> Path:
        return self.logs_dir or self.project_root / "logs"

    def resolved_cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_extra_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
