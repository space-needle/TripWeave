import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

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


def upload_path(grant_url: str) -> str:
    parsed = urlparse(grant_url)
    return parsed.path


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


def test_owner_uploads_images_and_completion_is_idempotent(
    client: TestClient, engine: Engine
) -> None:
    csrf_token = register(client)
    trip = create_trip(client, csrf_token)
    session_response = client.post(
        f"/trips/{trip['id']}/upload-sessions",
        headers={"x-csrf-token": csrf_token},
        json={
            "files": [
                {"filename": "same.jpg", "byteSize": 10, "mimeType": "image/jpeg"},
                {"filename": "same.jpg", "byteSize": 11, "mimeType": "image/jpeg"},
            ]
        },
    )
    assert session_response.status_code == 201
    upload_session = session_response.json()
    assert len(upload_session["files"]) == 2
    assert upload_session["files"][0]["objectKey"] != upload_session["files"][1]["objectKey"]

    first = upload_session["files"][0]
    put = client.put(
        upload_path(first["grant"]["url"]),
        content=b"0123456789",
        headers=first["grant"]["headers"],
    )
    assert put.status_code == 200

    complete = client.post(
        f"/upload-files/{first['id']}/complete",
        headers={"x-csrf-token": csrf_token},
    )
    assert complete.status_code == 200
    media_item_id = complete.json()["file"]["mediaItemId"]

    repeated = client.post(
        f"/upload-files/{first['id']}/complete",
        headers={"x-csrf-token": csrf_token},
    )
    assert repeated.status_code == 200
    assert repeated.json()["file"]["mediaItemId"] == media_item_id

    with engine.connect() as connection:
        media_count = connection.execute(text("SELECT count(*) FROM media_items")).scalar_one()
        job_count = connection.execute(text("SELECT count(*) FROM processing_jobs")).scalar_one()
        job_type = connection.execute(
            text("SELECT job_type FROM processing_jobs LIMIT 1")
        ).scalar_one()

    assert media_count == 1
    assert job_count == 1
    assert job_type == "ingest_media"


def test_upload_rejects_invalid_and_oversized_files(client: TestClient) -> None:
    csrf_token = register(client)
    trip = create_trip(client, csrf_token)

    no_csrf = client.post(
        f"/trips/{trip['id']}/upload-sessions",
        json={"files": [{"filename": "a.jpg", "byteSize": 1, "mimeType": "image/jpeg"}]},
    )
    assert no_csrf.status_code == 403

    zero_byte = client.post(
        f"/trips/{trip['id']}/upload-sessions",
        headers={"x-csrf-token": csrf_token},
        json={"files": [{"filename": "a.jpg", "byteSize": 0, "mimeType": "image/jpeg"}]},
    )
    assert zero_byte.status_code == 422

    wrong_type = client.post(
        f"/trips/{trip['id']}/upload-sessions",
        headers={"x-csrf-token": csrf_token},
        json={"files": [{"filename": "a.png", "byteSize": 1, "mimeType": "image/png"}]},
    )
    assert wrong_type.status_code == 400


def test_upload_completion_rejects_wrong_size(client: TestClient) -> None:
    csrf_token = register(client)
    trip = create_trip(client, csrf_token)
    created = client.post(
        f"/trips/{trip['id']}/upload-sessions",
        headers={"x-csrf-token": csrf_token},
        json={"files": [{"filename": "a.jpg", "byteSize": 10, "mimeType": "image/jpeg"}]},
    )
    upload_file = created.json()["files"][0]
    put = client.put(
        upload_path(upload_file["grant"]["url"]),
        content=b"short",
        headers=upload_file["grant"]["headers"],
    )
    assert put.status_code == 200

    complete = client.post(
        f"/upload-files/{upload_file['id']}/complete",
        headers={"x-csrf-token": csrf_token},
    )

    assert complete.status_code == 400


def test_second_user_cannot_complete_first_users_upload(
    client: TestClient, engine: Engine, tmp_path: Path
) -> None:
    url = get_test_database_url()
    if not url:
        pytest.skip("TRIPWEAVE_TEST_DATABASE_URL is not set")
    csrf_one = register(client, "upload-one@example.com")
    trip = create_trip(client, csrf_one)
    created = client.post(
        f"/trips/{trip['id']}/upload-sessions",
        headers={"x-csrf-token": csrf_one},
        json={"files": [{"filename": "a.jpg", "byteSize": 4, "mimeType": "image/jpeg"}]},
    )
    upload_file_id = created.json()["files"][0]["id"]

    settings = Settings(
        DATABASE_URL=PostgresDsn(url),
        TRIPWEAVE_BLOB_DIR=tmp_path,
        TRIPWEAVE_AUTH_RATE_LIMIT_MAX_ATTEMPTS=100,
    )
    client_two = TestClient(create_app(settings=settings, engine=engine))
    csrf_two = register(client_two, "upload-two@example.com")

    response = client_two.post(
        f"/upload-files/{upload_file_id}/complete",
        headers={"x-csrf-token": csrf_two},
    )

    assert response.status_code == 404
