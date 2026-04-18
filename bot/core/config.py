from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Bot
    bot_token: str
    owner_id: int
    required_channel_ids: list[int] = []

    # Encryption
    encryption_key: str

    # Database
    # Accepts Railway format: postgresql://user:pass@host:port/db
    # OR explicit asyncpg URL: postgresql+asyncpg://...
    database_url: str
    database_sync_url: str = ""   # auto-derived if empty

    # Redis
    redis_url: str

    # App
    debug: bool = False
    log_level: str = "INFO"
    session_health_check_interval: int = 1800

    @model_validator(mode="after")
    def fix_db_urls(self) -> Settings:
        """
        Railway provides DATABASE_URL as plain postgresql://...
        We need asyncpg (async) and psycopg2 (Alembic sync) variants.
        """
        url = self.database_url

        # Normalise to asyncpg for the app
        if url.startswith("postgresql://") or url.startswith("postgres://"):
            self.database_url = url.replace("postgres://", "postgresql://", 1)\
                                   .replace("postgresql://", "postgresql+asyncpg://", 1)

        # Auto-derive sync URL for Alembic if not set explicitly
        if not self.database_sync_url:
            self.database_sync_url = (
                self.database_url
                .replace("postgresql+asyncpg://", "postgresql+psycopg2://")
            )

        return self


settings = Settings()  # type: ignore[call-arg]
