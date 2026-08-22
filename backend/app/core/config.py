"""Application settings (env-driven)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:55432/specresearch"
    )
    s3_endpoint_url: str = "http://localhost:9010"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "specresearch"
    s3_region: str = "ap-southeast-1"
    jwt_secret: str = "dev-change-me-not-for-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7
    cors_origins: str = "http://localhost:3000"
    research_source_provider: str = "fake"
    research_provider_timeout_seconds: float = 15.0
    openalex_mailto: str | None = None
    openalex_api_key: str | None = None
    research_llm_provider: str = "fake"
    research_llm_model: str = "Qwen3.6-27B"
    fit_webui_api_key: str | None = None
    fit_webui_base_url: str = "https://ai-fit.hcmus.edu.vn/openai"
    fit_webui_timeout_seconds: float = 120.0
    fit_webui_max_tokens: int = 2_000

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]

    @property
    def database_url_sync(self) -> str:
        """Alembic/SQLAlchemy sync URL (psycopg3). App runtime stays on asyncpg."""
        return self.database_url.replace(
            "postgresql+asyncpg://", "postgresql+psycopg://", 1
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
