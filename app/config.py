from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Environment-backed settings shared by the API and command-line tools."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    GEMINI_API_KEY: str | None = None
    QUADRANT_API_KEY: str | None = None
    QUADRANT_URL: str | None = Field(
        default=None,
        validation_alias=AliasChoices("QUADRANT_URL", "QUADRANT_CLUSTER_ENDPOINT"),
    )
    QUADRANT_COLLECTION: str = "enterprise_rag"
    GROQ_API_KEY: str | None = None
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    GROQ_PLANNER_MODEL: str = "openai/gpt-oss-20b"

    LIVERAG_MAX_EXTRACTED_TEXT_BYTES: int = Field(default=500 * 1024, ge=1)
    LIVERAG_MAX_CONTENT_BLOCKS: int = Field(default=1000, ge=1)
    LIVERAG_EXTRACTION_MAX_FUTURE_SKEW_SECONDS: int = Field(default=300, ge=0)
    LIVERAG_EXTRACTION_MAX_AGE_DAYS: int = Field(default=30, ge=1)

    DATABASE_URL: str = f"sqlite:///{(PROJECT_ROOT / 'enterpriseiq.db').as_posix()}"
    ENTERPRISEIQ_API_KEY: str | None = None
    APP_ENV: str = "development"
    ENTERPRISEIQ_ORGANIZATION_ID: str = "local"
    ENTERPRISEIQ_ENABLE_EXTERNAL_RETRIEVAL: bool = False
    ENTERPRISEIQ_MAX_UPLOAD_BYTES: int = Field(default=10 * 1024 * 1024, ge=1)
    ENTERPRISEIQ_MAX_EXPANDED_UPLOAD_BYTES: int = Field(default=50 * 1024 * 1024, ge=1)
    ENTERPRISEIQ_MAX_QUERY_CHARS: int = Field(default=10_000, ge=1)
    ENTERPRISEIQ_MAX_RETRIEVAL_RESULTS: int = Field(default=20, ge=1)
    ENTERPRISEIQ_PROCESSED_DATA_DIR: str = "processed_data"
    ENTERPRISEIQ_RATE_LIMIT_PER_MINUTE: int = Field(default=120, ge=1)
    ENTERPRISEIQ_CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
