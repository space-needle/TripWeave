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
    session_cookie_name: str = Field(default="tripweave_session", alias="TRIPWEAVE_SESSION_COOKIE")
    csrf_cookie_name: str = Field(default="tripweave_csrf", alias="TRIPWEAVE_CSRF_COOKIE")
    session_lifetime_seconds: int = Field(default=604800, ge=60, alias="TRIPWEAVE_SESSION_SECONDS")
    auth_rate_limit_window_seconds: int = Field(
        default=60, ge=1, alias="TRIPWEAVE_AUTH_RATE_LIMIT_WINDOW_SECONDS"
    )
    auth_rate_limit_max_attempts: int = Field(
        default=10, ge=1, alias="TRIPWEAVE_AUTH_RATE_LIMIT_MAX_ATTEMPTS"
    )
    allowed_web_origins: str = Field(
        default="http://localhost:3000", alias="TRIPWEAVE_ALLOWED_WEB_ORIGINS"
    )

    @property
    def secure_cookies(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_web_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
