from pydantic import PostgresDsn

from tripweave.config import Settings
from tripweave.entrypoints.api.main import public_asset_base_url


def settings_for(
    *,
    environment: str = "production",
    public_api_base_url: str = "http://localhost:8000",
) -> Settings:
    return Settings(
        DATABASE_URL=PostgresDsn("postgresql+psycopg://user:pass@localhost:5432/tripweave"),
        TRIPWEAVE_ENV=environment,
        TRIPWEAVE_PUBLIC_API_BASE_URL=public_api_base_url,
    )


def test_public_assets_use_request_origin_when_configured_base_url_is_loopback() -> None:
    settings = settings_for()

    assert (
        public_asset_base_url(settings, "https://tripweave.example.com/")
        == "https://tripweave.example.com"
    )


def test_public_assets_keep_configured_public_base_url() -> None:
    settings = settings_for(public_api_base_url="https://cdn-api.example.com")

    assert (
        public_asset_base_url(settings, "https://tripweave.example.com/")
        == "https://cdn-api.example.com"
    )


def test_local_public_assets_keep_test_client_origin() -> None:
    settings = settings_for(environment="local")

    assert public_asset_base_url(settings, "http://testserver/") == "http://testserver"
