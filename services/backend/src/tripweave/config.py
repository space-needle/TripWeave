from functools import lru_cache
from pathlib import Path

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = Field(default="local", alias="TRIPWEAVE_ENV")
    database_url: PostgresDsn = Field(
        default=PostgresDsn(
            "postgresql+psycopg://tripweave:tripweave_local_password@localhost:5432/tripweave"
        ),
        alias="DATABASE_URL",
    )
    log_level: str = Field(default="INFO", alias="TRIPWEAVE_LOG_LEVEL")
    blob_dir: Path = Field(default=Path("/var/lib/tripweave/blobs"), alias="TRIPWEAVE_BLOB_DIR")
    worker_heartbeat_seconds: int = Field(
        default=30, ge=1, alias="TRIPWEAVE_WORKER_HEARTBEAT_SECONDS"
    )
    worker_stale_seconds: int = Field(default=90, ge=1, alias="TRIPWEAVE_WORKER_STALE_SECONDS")


@lru_cache
def get_settings() -> Settings:
    return Settings()
