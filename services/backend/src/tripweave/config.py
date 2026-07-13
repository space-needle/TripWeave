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
    worker_concurrency: int = Field(default=1, ge=1, alias="TRIPWEAVE_WORKER_CONCURRENCY")
    worker_poll_seconds: float = Field(default=2.0, ge=0.1, alias="TRIPWEAVE_WORKER_POLL_SECONDS")
    worker_lock_timeout_seconds: int = Field(
        default=300, ge=1, alias="TRIPWEAVE_WORKER_LOCK_TIMEOUT_SECONDS"
    )
    session_cookie_name: str = Field(default="tripweave_session", alias="TRIPWEAVE_SESSION_COOKIE")
    guest_session_cookie_name: str = Field(
        default="tripweave_guest_session", alias="TRIPWEAVE_GUEST_SESSION_COOKIE"
    )
    csrf_cookie_name: str = Field(default="tripweave_csrf", alias="TRIPWEAVE_CSRF_COOKIE")
    session_lifetime_seconds: int = Field(default=604800, ge=60, alias="TRIPWEAVE_SESSION_SECONDS")
    guest_session_lifetime_seconds: int = Field(
        default=604800, ge=60, alias="TRIPWEAVE_GUEST_SESSION_SECONDS"
    )
    invitation_lifetime_seconds: int = Field(
        default=604800, ge=60, alias="TRIPWEAVE_INVITATION_SECONDS"
    )
    auth_rate_limit_window_seconds: int = Field(
        default=60, ge=1, alias="TRIPWEAVE_AUTH_RATE_LIMIT_WINDOW_SECONDS"
    )
    auth_rate_limit_max_attempts: int = Field(
        default=10, ge=1, alias="TRIPWEAVE_AUTH_RATE_LIMIT_MAX_ATTEMPTS"
    )
    allowed_web_origins: str = Field(
        default="http://localhost:3000", alias="TRIPWEAVE_ALLOWED_WEB_ORIGINS"
    )
    public_api_base_url: str = Field(
        default="http://localhost:8000", alias="TRIPWEAVE_PUBLIC_API_BASE_URL"
    )
    storage_signing_secret: str = Field(
        default="local-development-upload-signing-secret",
        alias="TRIPWEAVE_STORAGE_SIGNING_SECRET",
        min_length=16,
    )
    storage_store_aliases: str = Field(
        default="media_private,story_published", alias="TRIPWEAVE_STORAGE_STORE_ALIASES"
    )
    upload_grant_lifetime_seconds: int = Field(
        default=900, ge=1, alias="TRIPWEAVE_UPLOAD_GRANT_SECONDS"
    )
    upload_max_files_per_trip: int = Field(
        default=500, ge=1, alias="TRIPWEAVE_UPLOAD_MAX_FILES_PER_TRIP"
    )
    upload_max_file_bytes: int = Field(
        default=25 * 1024 * 1024, ge=1, alias="TRIPWEAVE_UPLOAD_MAX_FILE_BYTES"
    )
    upload_max_trip_bytes: int = Field(
        default=5 * 1024 * 1024 * 1024, ge=1, alias="TRIPWEAVE_UPLOAD_MAX_TRIP_BYTES"
    )
    upload_allowed_extensions: str = Field(
        default=".jpg,.jpeg,.heic", alias="TRIPWEAVE_UPLOAD_ALLOWED_EXTENSIONS"
    )
    upload_allowed_mime_types: str = Field(
        default="image/jpeg,image/heic,image/heif",
        alias="TRIPWEAVE_UPLOAD_ALLOWED_MIME_TYPES",
    )
    media_max_pixels: int = Field(default=80_000_000, ge=1, alias="TRIPWEAVE_MEDIA_MAX_PIXELS")
    media_max_decoded_bytes: int = Field(
        default=512 * 1024 * 1024, ge=1, alias="TRIPWEAVE_MEDIA_MAX_DECODED_BYTES"
    )
    media_thumbnail_max_px: int = Field(default=480, ge=1, alias="TRIPWEAVE_MEDIA_THUMBNAIL_MAX_PX")
    media_preview_max_px: int = Field(default=1600, ge=1, alias="TRIPWEAVE_MEDIA_PREVIEW_MAX_PX")

    @property
    def secure_cookies(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_web_origins.split(",") if origin.strip()]

    @property
    def store_aliases(self) -> set[str]:
        return {alias.strip() for alias in self.storage_store_aliases.split(",") if alias.strip()}

    @property
    def allowed_upload_extensions(self) -> set[str]:
        return {
            extension.strip().lower()
            for extension in self.upload_allowed_extensions.split(",")
            if extension.strip()
        }

    @property
    def allowed_upload_mime_types(self) -> set[str]:
        return {
            mime_type.strip().lower()
            for mime_type in self.upload_allowed_mime_types.split(",")
            if mime_type.strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
