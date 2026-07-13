import os
from collections.abc import Iterator
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import PostgresDsn
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from alembic import command
from tripweave.adapters.blob_store_factory import create_blob_store
from tripweave.config import Settings, get_settings
from tripweave.entrypoints.api.main import create_app
from tripweave.entrypoints.worker.main import ClaimedJob, claim_job, handle_job


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


def jpeg_bytes(size: tuple[int, int] = (32, 24)) -> bytes:
    image = Image.new("RGB", size, "purple")
    output = BytesIO()
    image.save(output, format="JPEG")
    return output.getvalue()


def upload_completed_jpeg(
    client: TestClient,
    csrf_token: str,
    trip_id: object,
    payload: bytes,
    filename: str = "image.jpg",
) -> str:
    created = client.post(
        f"/trips/{trip_id}/upload-sessions",
        headers={"x-csrf-token": csrf_token},
        json={
            "files": [{"filename": filename, "byteSize": len(payload), "mimeType": "image/jpeg"}]
        },
    )
    assert created.status_code == 201
    upload_file = created.json()["files"][0]
    put = client.put(
        upload_path(upload_file["grant"]["url"]),
        content=payload,
        headers=upload_file["grant"]["headers"],
    )
    assert put.status_code == 200
    completed = client.post(
        f"/upload-files/{upload_file['id']}/complete",
        headers={"x-csrf-token": csrf_token},
    )
    assert completed.status_code == 200
    return str(completed.json()["file"]["mediaItemId"])


def create_invitation(client: TestClient, csrf_token: str, trip_id: object) -> dict[str, object]:
    response = client.post(
        f"/trips/{trip_id}/invitations",
        headers={"x-csrf-token": csrf_token},
        json={},
    )
    assert response.status_code == 201
    return dict(response.json())


def token_from_invite_url(invite_url: str) -> str:
    return invite_url.rsplit("/", 1)[-1]


def accept_invitation(client: TestClient, token: str, display_name: str = "Guest") -> str:
    response = client.post(
        f"/invitations/{token}/accept",
        json={"displayName": display_name},
    )
    assert response.status_code == 200
    return str(response.json()["csrfToken"])


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


def test_owner_invites_guest_and_guest_uploads_with_attribution(
    client: TestClient, engine: Engine, tmp_path: Path
) -> None:
    url = get_test_database_url()
    assert url is not None
    csrf_owner = register(client, "invite-owner@example.com")
    trip = create_trip(client, csrf_owner)
    invitation = create_invitation(client, csrf_owner, trip["id"])
    token = token_from_invite_url(str(invitation["inviteUrl"]))

    guest_client = TestClient(
        create_app(
            settings=Settings(
                DATABASE_URL=PostgresDsn(url),
                TRIPWEAVE_BLOB_DIR=tmp_path,
                TRIPWEAVE_AUTH_RATE_LIMIT_MAX_ATTEMPTS=100,
            ),
            engine=engine,
        )
    )
    preview = guest_client.get(f"/invitations/{token}")
    assert preview.status_code == 200
    assert preview.json()["title"] == "Kyoto"
    csrf_guest = accept_invitation(guest_client, token, "Traveler")
    repeated = guest_client.post(
        f"/invitations/{token}/accept",
        json={"displayName": "Traveler Again"},
    )
    assert repeated.status_code == 200
    csrf_guest = str(repeated.json()["csrfToken"])
    other_browser = TestClient(
        create_app(
            settings=Settings(
                DATABASE_URL=PostgresDsn(url),
                TRIPWEAVE_BLOB_DIR=tmp_path,
                TRIPWEAVE_AUTH_RATE_LIMIT_MAX_ATTEMPTS=100,
            ),
            engine=engine,
        )
    )
    reused_elsewhere = other_browser.post(
        f"/invitations/{token}/accept",
        json={"displayName": "Imposter"},
    )
    assert reused_elsewhere.status_code == 404

    media_item_id = upload_completed_jpeg(
        guest_client,
        csrf_guest,
        trip["id"],
        jpeg_bytes(),
        filename="guest.jpg",
    )

    guest_media = guest_client.get(f"/trips/{trip['id']}/media")
    assert guest_media.status_code == 200
    assert guest_media.json()["media"][0]["id"] == media_item_id
    assert guest_media.json()["media"][0]["contributor"] == "Traveler"

    owner_media = client.get(f"/trips/{trip['id']}/media")
    assert owner_media.status_code == 200
    assert owner_media.json()["media"][0]["contributor"] == "Traveler"


def test_invitation_rejects_expired_revoked_and_malformed(
    client: TestClient, engine: Engine
) -> None:
    csrf_owner = register(client, "bad-invite-owner@example.com")
    trip = create_trip(client, csrf_owner)
    invitation = create_invitation(client, csrf_owner, trip["id"])
    token = token_from_invite_url(str(invitation["inviteUrl"]))

    assert client.get("/invitations/not-a-real-token").status_code == 404

    with engine.begin() as connection:
        connection.execute(text("UPDATE trip_invitations SET expires_at = '2020-01-01'"))
    assert client.get(f"/invitations/{token}").status_code == 404

    invitation = create_invitation(client, csrf_owner, trip["id"])
    token = token_from_invite_url(str(invitation["inviteUrl"]))
    revoked = client.delete(
        f"/invitations/{invitation['id']}",
        headers={"x-csrf-token": csrf_owner},
    )
    assert revoked.status_code == 204
    assert (
        client.post(f"/invitations/{token}/accept", json={"displayName": "Nope"}).status_code == 404
    )


def test_guest_cannot_access_other_trip_or_alter_other_contributor_media(
    client: TestClient, engine: Engine, tmp_path: Path
) -> None:
    url = get_test_database_url()
    assert url is not None
    csrf_owner = register(client, "multi-guest-owner@example.com")
    trip_one = create_trip(client, csrf_owner, "One")
    trip_two = create_trip(client, csrf_owner, "Two")

    guest_one = TestClient(
        create_app(
            settings=Settings(DATABASE_URL=PostgresDsn(url), TRIPWEAVE_BLOB_DIR=tmp_path),
            engine=engine,
        )
    )
    guest_two = TestClient(
        create_app(
            settings=Settings(DATABASE_URL=PostgresDsn(url), TRIPWEAVE_BLOB_DIR=tmp_path),
            engine=engine,
        )
    )
    invite_one = create_invitation(client, csrf_owner, trip_one["id"])
    invite_two = create_invitation(client, csrf_owner, trip_one["id"])
    csrf_guest_one = accept_invitation(
        guest_one, token_from_invite_url(str(invite_one["inviteUrl"])), "One"
    )
    csrf_guest_two = accept_invitation(
        guest_two, token_from_invite_url(str(invite_two["inviteUrl"])), "Two"
    )

    media_one = upload_completed_jpeg(guest_one, csrf_guest_one, trip_one["id"], jpeg_bytes())
    upload_completed_jpeg(
        guest_two, csrf_guest_two, trip_one["id"], jpeg_bytes(), filename="two.jpg"
    )

    assert guest_one.get(f"/trips/{trip_two['id']}/media").status_code == 404
    denied = guest_two.patch(
        f"/media/{media_one}",
        headers={"x-csrf-token": csrf_guest_two},
        json={"visibility": "story"},
    )
    assert denied.status_code == 404


def test_removed_contributor_loses_future_access_but_media_ownership_remains(
    client: TestClient, engine: Engine, tmp_path: Path
) -> None:
    url = get_test_database_url()
    assert url is not None
    csrf_owner = register(client, "remove-owner@example.com")
    trip = create_trip(client, csrf_owner)
    invitation = create_invitation(client, csrf_owner, trip["id"])
    guest_client = TestClient(
        create_app(
            settings=Settings(DATABASE_URL=PostgresDsn(url), TRIPWEAVE_BLOB_DIR=tmp_path),
            engine=engine,
        )
    )
    csrf_guest = accept_invitation(
        guest_client, token_from_invite_url(str(invitation["inviteUrl"])), "Removed"
    )
    media_item_id = upload_completed_jpeg(guest_client, csrf_guest, trip["id"], jpeg_bytes())
    member_id = guest_client.get("/guest/me").json()["id"]

    removed = client.delete(f"/trip-members/{member_id}", headers={"x-csrf-token": csrf_owner})
    assert removed.status_code == 204
    assert guest_client.get(f"/trips/{trip['id']}/media").status_code == 401

    with engine.connect() as connection:
        owner = connection.execute(
            text(
                """
                SELECT tm.display_name
                FROM media_items mi
                JOIN trip_members tm ON tm.id = mi.contributor_member_id
                WHERE mi.id = :id
                """
            ),
            {"id": media_item_id},
        ).scalar_one()
    assert owner == "Removed"


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


def test_worker_ingests_media_and_rerun_creates_no_duplicate_assets(
    client: TestClient, engine: Engine, tmp_path: Path
) -> None:
    url = get_test_database_url()
    assert url is not None
    settings = Settings(
        DATABASE_URL=PostgresDsn(url),
        TRIPWEAVE_BLOB_DIR=tmp_path,
        TRIPWEAVE_AUTH_RATE_LIMIT_MAX_ATTEMPTS=100,
    )
    csrf_token = register(client, "worker-owner@example.com")
    trip = create_trip(client, csrf_token)
    media_item_id = upload_completed_jpeg(client, csrf_token, trip["id"], jpeg_bytes())
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    blob_store = create_blob_store(settings)

    with session_factory() as db:
        job = claim_job(db, settings, "test-worker")
    assert job is not None
    handle_job(settings, session_factory, blob_store, "test-worker", job)

    with engine.connect() as connection:
        state = connection.execute(
            text("SELECT processing_state FROM media_items WHERE id = :id"),
            {"id": media_item_id},
        ).scalar_one()
        asset_count = connection.execute(text("SELECT count(*) FROM media_assets")).scalar_one()
        job_state = connection.execute(text("SELECT state FROM processing_jobs")).scalar_one()

    assert state == "ready"
    assert asset_count == 2
    assert job_state == "succeeded"

    handle_job(
        settings,
        session_factory,
        blob_store,
        "test-worker",
        ClaimedJob(
            id=job.id,
            job_type=job.job_type,
            target_type=job.target_type,
            target_id=job.target_id,
            attempts=1,
            max_attempts=3,
        ),
    )

    with engine.connect() as connection:
        asset_count_after = connection.execute(
            text("SELECT count(*) FROM media_assets")
        ).scalar_one()

    assert asset_count_after == 2


def test_worker_recovers_expired_lock(client: TestClient, engine: Engine, tmp_path: Path) -> None:
    url = get_test_database_url()
    assert url is not None
    settings = Settings(
        DATABASE_URL=PostgresDsn(url),
        TRIPWEAVE_BLOB_DIR=tmp_path,
        TRIPWEAVE_AUTH_RATE_LIMIT_MAX_ATTEMPTS=100,
        TRIPWEAVE_WORKER_LOCK_TIMEOUT_SECONDS=1,
    )
    csrf_token = register(client, "lock-owner@example.com")
    trip = create_trip(client, csrf_token)
    upload_completed_jpeg(client, csrf_token, trip["id"], jpeg_bytes())
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    with session_factory() as db:
        first = claim_job(db, settings, "test-worker-one")
    assert first is not None
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE processing_jobs SET locked_at = '2020-01-01T00:00:00+00:00'")
        )
    with session_factory() as db:
        reclaimed = claim_job(db, settings, "test-worker-two")

    assert reclaimed is not None
    assert reclaimed.id == first.id
    assert reclaimed.attempts == 2
