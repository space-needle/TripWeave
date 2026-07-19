from pydantic import PostgresDsn

from tripweave.config import LOCAL_WEB_ORIGIN_REGEX, Settings


def settings_for(environment: str = "local") -> Settings:
    return Settings(
        DATABASE_URL=PostgresDsn("postgresql+psycopg://user:pass@localhost:5432/tripweave"),
        TRIPWEAVE_ENV=environment,
    )


def test_local_environment_allows_private_lan_web_origin() -> None:
    settings = settings_for()

    assert settings.cors_origin_regex == LOCAL_WEB_ORIGIN_REGEX
    assert settings.web_origin_is_allowed("http://192.168.1.25:3000")


def test_local_environment_rejects_wrong_port_for_lan_web_origin() -> None:
    settings = settings_for()

    assert not settings.web_origin_is_allowed("http://192.168.1.25:4000")


def test_production_environment_requires_explicit_web_origin() -> None:
    settings = settings_for("production")

    assert settings.cors_origin_regex is None
    assert not settings.web_origin_is_allowed("http://192.168.1.25:3000")
