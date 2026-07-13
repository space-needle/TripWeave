import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import PostgresDsn
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from alembic import command
from tripweave.config import Settings, get_settings
from tripweave.entrypoints.api.main import create_app


def get_test_database_url() -> str | None:
    return os.environ.get("TRIPWEAVE_TEST_DATABASE_URL")


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    url = get_test_database_url()
    if not url:
        pytest.skip("TRIPWEAVE_TEST_DATABASE_URL is not set")
    engine = create_engine(url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def client(engine: Engine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    url = get_test_database_url()
    assert url is not None
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    settings = Settings(
        DATABASE_URL=PostgresDsn(url),
        TRIPWEAVE_BLOB_DIR=tmp_path,
        TRIPWEAVE_AUTH_RATE_LIMIT_MAX_ATTEMPTS=100,
    )
    with TestClient(create_app(settings=settings, engine=engine)) as test_client:
        yield test_client
    command.downgrade(config, "base")
    get_settings.cache_clear()


def register(client: TestClient, email: str = "owner@example.com") -> str:
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "long-enough-password",
            "displayName": "Owner",
        },
    )
    assert response.status_code == 201
    return str(response.json()["csrfToken"])


def create_trip(client: TestClient, csrf_token: str, title: str = "Kyoto") -> dict[str, object]:
    response = client.post(
        "/trips",
        headers={"x-csrf-token": csrf_token},
        json={"title": title, "timezoneId": "Asia/Tokyo"},
    )
    assert response.status_code == 201
    return dict(response.json())


def test_authentication_lifecycle_and_trip_management(client: TestClient) -> None:
    csrf_token = register(client)

    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "owner@example.com"

    forbidden = client.post("/trips", json={"title": "No CSRF"})
    assert forbidden.status_code == 403

    trip = create_trip(client, csrf_token)
    trip_id = str(trip["id"])
    assert trip["role"] == "owner"

    updated = client.patch(
        f"/trips/{trip_id}",
        headers={"x-csrf-token": csrf_token},
        json={"title": "Kyoto and Osaka"},
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Kyoto and Osaka"

    deleted = client.delete(f"/trips/{trip_id}", headers={"x-csrf-token": csrf_token})
    assert deleted.status_code == 204
    assert client.get(f"/trips/{trip_id}").status_code == 404


def test_session_revocation_on_logout(client: TestClient) -> None:
    csrf_token = register(client)

    logout = client.post("/auth/logout", headers={"x-csrf-token": csrf_token})

    assert logout.status_code == 200
    assert client.get("/auth/me").status_code == 401


def test_session_expiration_is_rejected(client: TestClient, engine: Engine) -> None:
    register(client)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE sessions SET expires_at = :expires_at"),
            {"expires_at": datetime(2020, 1, 1, tzinfo=UTC)},
        )

    assert client.get("/auth/me").status_code == 401


def test_second_user_cannot_access_private_trip(
    client: TestClient, engine: Engine, tmp_path: Path
) -> None:
    url = get_test_database_url()
    if not url:
        pytest.skip("TRIPWEAVE_TEST_DATABASE_URL is not set")
    settings = Settings(
        DATABASE_URL=PostgresDsn(url),
        TRIPWEAVE_BLOB_DIR=tmp_path,
        TRIPWEAVE_AUTH_RATE_LIMIT_MAX_ATTEMPTS=100,
    )
    client_two = TestClient(create_app(settings=settings, engine=engine))
    csrf_one = register(client, "one@example.com")
    trip = create_trip(client, csrf_one)
    register(client_two, "two@example.com")

    response = client_two.get(f"/trips/{trip['id']}")

    assert response.status_code == 404
