import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, cast
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
from tripweave.adapters.manual_geocoder import ManualGeocoder
from tripweave.config import Settings, get_settings
from tripweave.domain.storage import BlobRef
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


def register(
    client: TestClient,
    email: str = "owner@example.com",
    display_name: str = "Owner",
) -> str:
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "long-enough-password",
            "displayName": display_name,
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


def insert_ready_media_for_reconstruction(
    engine: Engine,
    *,
    trip_id: str,
    member_id: str,
    filename: str,
    captured_at: datetime | None,
    latitude: float | None,
    longitude: float | None,
    sha256: str,
    perceptual_hash: str | None = None,
    capture_device_id: str | None = None,
) -> str:
    with engine.begin() as connection:
        media_id = connection.execute(
            text(
                """
                INSERT INTO media_items (
                    trip_id, contributor_member_id, media_type, original_filename,
                    declared_mime_type, byte_size, original_store_alias,
                    original_object_key, original_captured_at_utc,
                    original_utc_offset_minutes, effective_captured_at_utc,
                    effective_location, time_source, location_source,
                    time_confidence, location_confidence, sha256,
                    perceptual_hash, capture_device_id,
                    processing_state, visibility
                )
                VALUES (
                    CAST(:trip_id AS uuid), CAST(:member_id AS uuid), 'photo', :filename,
                    'image/jpeg', 100, 'media_private',
                    :object_key, CAST(:captured_at AS timestamptz),
                    540, CAST(:captured_at AS timestamptz),
                    CASE
                        WHEN CAST(:latitude AS double precision) IS NULL THEN NULL
                        ELSE ST_SetSRID(
                            ST_MakePoint(
                                CAST(:longitude AS double precision),
                                CAST(:latitude AS double precision)
                            ),
                            4326
                        )::geography
                    END,
                    CASE
                        WHEN CAST(:captured_at AS timestamptz) IS NULL
                        THEN 'unknown'
                        ELSE 'original_metadata'
                    END,
                    CASE
                        WHEN CAST(:latitude AS double precision) IS NULL
                        THEN 'unknown'
                        ELSE 'original_metadata'
                    END,
                    CASE WHEN CAST(:captured_at AS timestamptz) IS NULL THEN NULL ELSE 1.0 END,
                    CASE WHEN CAST(:latitude AS double precision) IS NULL THEN NULL ELSE 1.0 END,
                    :sha256, :perceptual_hash, CAST(:capture_device_id AS uuid), 'ready', 'trip'
                )
                RETURNING id
                """
            ),
            {
                "trip_id": trip_id,
                "member_id": member_id,
                "filename": filename,
                "object_key": f"tests/{filename}",
                "captured_at": captured_at,
                "latitude": latitude,
                "longitude": longitude,
                "sha256": sha256,
                "perceptual_hash": perceptual_hash,
                "capture_device_id": capture_device_id,
            },
        ).scalar_one()
    return str(media_id)


def insert_capture_device(
    engine: Engine,
    *,
    trip_id: str,
    member_id: str,
    device_key: str,
    display_name: str,
) -> str:
    with engine.begin() as connection:
        return str(
            connection.execute(
                text(
                    """
                    INSERT INTO capture_devices (
                        trip_id, contributor_member_id, device_key, display_name
                    )
                    VALUES (
                        CAST(:trip_id AS uuid), CAST(:member_id AS uuid),
                        :device_key, :display_name
                    )
                    RETURNING id
                    """
                ),
                {
                    "trip_id": trip_id,
                    "member_id": member_id,
                    "device_key": device_key,
                    "display_name": display_name,
                },
            ).scalar_one()
        )


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


def insert_sanitized_assets(client: TestClient, engine: Engine, media_id: str) -> None:
    app = cast(Any, client.app)
    blob_store = app.state.blob_store
    for asset_type, payload in {
        "thumbnail": b"thumbnail-webp",
        "display": b"display-webp",
    }.items():
        object_key = f"tests/assets/{media_id}/{asset_type}.webp"
        metadata = blob_store.put(
            BlobRef(store_alias="media_private", object_key=object_key),
            BytesIO(payload),
            max_size_bytes=1024,
            content_type="image/webp",
        )
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO media_assets (
                        media_item_id, asset_type, store_alias, object_key,
                        mime_type, width, height, byte_size, checksum, metadata_stripped
                    )
                    VALUES (
                        CAST(:media_id AS uuid), :asset_type, 'media_private',
                        :object_key, 'image/webp', 32, 24, :byte_size,
                        :checksum, true
                    )
                    """
                ),
                {
                    "media_id": media_id,
                    "asset_type": asset_type,
                    "object_key": object_key,
                    "byte_size": metadata.size_bytes,
                    "checksum": metadata.checksum,
                },
            )


def run_one_worker_job(client: TestClient, engine: Engine) -> None:
    app = cast(Any, client.app)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        job = claim_job(db, app.state.settings, "test-worker")
    assert isinstance(job, ClaimedJob)
    handle_job(
        app.state.settings,
        session_factory,
        app.state.blob_store,
        app.state.geocoder,
        "test-worker",
        job,
    )


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


def accept_invitation(
    client: TestClient,
    token: str,
    csrf_token: str,
    display_name: str | None = None,
) -> dict[str, object]:
    payload = {"displayName": display_name} if display_name is not None else {}
    response = client.post(
        f"/invitations/{token}/accept",
        headers={"x-csrf-token": csrf_token},
        json=payload,
    )
    assert response.status_code == 200
    return dict(response.json())


def test_authentication_lifecycle_and_trip_management(client: TestClient) -> None:
    csrf_token = register(client)

    me = client.get("/auth/me", headers={"x-request-id": "test-request-id"})
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "owner@example.com"
    assert me.headers["x-request-id"] == "test-request-id"

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


def test_local_ops_endpoint_is_authenticated(client: TestClient) -> None:
    assert client.get("/ops/local-mvp").status_code == 401

    register(client, "ops-owner@example.com")
    response = client.get("/ops/local-mvp")

    assert response.status_code == 200
    body = response.json()
    assert "jobStates" in body
    assert "mediaStates" in body
    assert "uploadStates" in body
    assert "reviewStates" in body
    assert "shareLinkStates" in body
    assert "recentFailures" in body
    assert "counts" in body
    assert body["counts"]["users"] >= 1
    assert "limits" in body
    assert body["limits"]["maxFilesPerTrip"] >= 1
    assert "environment" in body
    assert "media_private" in body["environment"]["storageAliases"]
    assert "story_published" in body["environment"]["storageAliases"]
    assert "storage" in body
    assert "worker" in body
    assert "warnings" in body
    assert body["warnings"]["workerStale"] is True


def test_trip_timezone_must_be_iana_identifier(client: TestClient) -> None:
    csrf_token = register(client, "timezone-owner@example.com")

    created = client.post(
        "/trips",
        headers={"x-csrf-token": csrf_token},
        json={"title": "Seoul", "timezoneId": "Korea"},
    )
    assert created.status_code == 422

    trip = create_trip(client, csrf_token, "Seoul")
    updated = client.patch(
        f"/trips/{trip['id']}",
        headers={"x-csrf-token": csrf_token},
        json={"timezoneId": "Korea"},
    )
    assert updated.status_code == 422


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


def test_owner_invites_account_contributor_and_contributor_uploads_with_attribution(
    client: TestClient, engine: Engine, tmp_path: Path
) -> None:
    url = get_test_database_url()
    assert url is not None
    csrf_owner = register(client, "invite-owner@example.com")
    trip = create_trip(client, csrf_owner)
    invitation = create_invitation(client, csrf_owner, trip["id"])
    token = token_from_invite_url(str(invitation["inviteUrl"]))

    contributor_client = TestClient(
        create_app(
            settings=Settings(
                DATABASE_URL=PostgresDsn(url),
                TRIPWEAVE_BLOB_DIR=tmp_path,
                TRIPWEAVE_AUTH_RATE_LIMIT_MAX_ATTEMPTS=100,
            ),
            engine=engine,
        )
    )
    preview = contributor_client.get(f"/invitations/{token}")
    assert preview.status_code == 200
    assert preview.json()["title"] == "Kyoto"
    unauthenticated = contributor_client.post(
        f"/invitations/{token}/accept",
        json={"displayName": "Traveler"},
    )
    assert unauthenticated.status_code == 401
    csrf_contributor = register(contributor_client, "traveler@example.com", "Traveler")
    missing_csrf = contributor_client.post(
        f"/invitations/{token}/accept",
        json={},
    )
    assert missing_csrf.status_code == 403
    accepted = accept_invitation(contributor_client, token, csrf_contributor)
    assert accepted["displayName"] == "Traveler"
    repeated = contributor_client.post(
        f"/invitations/{token}/accept",
        headers={"x-csrf-token": csrf_contributor},
        json={},
    )
    assert repeated.status_code == 200
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
    csrf_other = register(other_browser, "imposter@example.com")
    reused_elsewhere = other_browser.post(
        f"/invitations/{token}/accept",
        headers={"x-csrf-token": csrf_other},
        json={},
    )
    assert reused_elsewhere.status_code == 404

    media_item_id = upload_completed_jpeg(
        contributor_client,
        csrf_contributor,
        trip["id"],
        jpeg_bytes(),
        filename="guest.jpg",
    )

    contributor_media = contributor_client.get(f"/trips/{trip['id']}/media")
    assert contributor_media.status_code == 200
    assert contributor_media.json()["media"][0]["id"] == media_item_id
    assert contributor_media.json()["media"][0]["contributor"] == "Traveler"

    owner_media = client.get(f"/trips/{trip['id']}/media")
    assert owner_media.status_code == 200
    assert owner_media.json()["media"][0]["contributor"] == "Traveler"


def test_account_invitation_adds_trip_to_contributor_library(
    client: TestClient, engine: Engine, tmp_path: Path
) -> None:
    url = get_test_database_url()
    assert url is not None
    csrf_owner = register(client, "library-owner@example.com")
    trip = create_trip(client, csrf_owner)
    invitation = create_invitation(client, csrf_owner, trip["id"])
    token = token_from_invite_url(str(invitation["inviteUrl"]))

    contributor_client = TestClient(
        create_app(
            settings=Settings(DATABASE_URL=PostgresDsn(url), TRIPWEAVE_BLOB_DIR=tmp_path),
            engine=engine,
        )
    )
    csrf_contributor = register(
        contributor_client, "library-contributor@example.com", "Library Contributor"
    )
    accepted = accept_invitation(contributor_client, token, csrf_contributor)

    trips = contributor_client.get("/trips")
    assert trips.status_code == 200
    assert trips.json()["trips"][0]["id"] == trip["id"]
    assert trips.json()["trips"][0]["role"] == "contributor"
    assert trips.json()["trips"][0]["memberId"] == accepted["id"]


def test_same_account_reuses_member_across_new_invitations(
    client: TestClient, engine: Engine, tmp_path: Path
) -> None:
    url = get_test_database_url()
    assert url is not None
    csrf_owner = register(client, "reuse-owner@example.com")
    trip = create_trip(client, csrf_owner)
    first_invitation = create_invitation(client, csrf_owner, trip["id"])

    contributor_client = TestClient(
        create_app(
            settings=Settings(DATABASE_URL=PostgresDsn(url), TRIPWEAVE_BLOB_DIR=tmp_path),
            engine=engine,
        )
    )
    csrf_contributor = register(
        contributor_client, "reuse-contributor@example.com", "Reuse Contributor"
    )
    first_member = accept_invitation(
        contributor_client,
        token_from_invite_url(str(first_invitation["inviteUrl"])),
        csrf_contributor,
    )
    media_item_id = upload_completed_jpeg(
        contributor_client,
        csrf_contributor,
        trip["id"],
        jpeg_bytes(),
        filename="first-link.jpg",
    )

    second_invitation = create_invitation(client, csrf_owner, trip["id"])
    second_member = accept_invitation(
        contributor_client,
        token_from_invite_url(str(second_invitation["inviteUrl"])),
        csrf_contributor,
    )

    assert second_member["id"] == first_member["id"]
    media_response = contributor_client.get(f"/trips/{trip['id']}/media")
    assert media_response.status_code == 200
    media_by_id = {item["id"]: item for item in media_response.json()["media"]}
    assert media_by_id[media_item_id]["contributorMemberId"] == first_member["id"]
    assert media_by_id[media_item_id]["canUpdateVisibility"] is True


def test_account_contributor_can_view_shared_story_without_editing(
    client: TestClient, engine: Engine, tmp_path: Path
) -> None:
    url = get_test_database_url()
    assert url is not None
    csrf_owner = register(client, "story-owner@example.com")
    trip = create_trip(client, csrf_owner)
    invitation = create_invitation(client, csrf_owner, trip["id"])

    contributor_client = TestClient(
        create_app(
            settings=Settings(DATABASE_URL=PostgresDsn(url), TRIPWEAVE_BLOB_DIR=tmp_path),
            engine=engine,
        )
    )
    csrf_contributor = register(
        contributor_client, "story-contributor@example.com", "Story Contributor"
    )
    accepted = accept_invitation(
        contributor_client,
        token_from_invite_url(str(invitation["inviteUrl"])),
        csrf_contributor,
    )
    contributor_member_id = str(accepted["id"])
    with engine.connect() as connection:
        owner_member_id = str(
            connection.execute(
                text(
                    """
                    SELECT id
                    FROM trip_members
                    WHERE trip_id = CAST(:trip_id AS uuid) AND role = 'owner'
                    """
                ),
                {"trip_id": trip["id"]},
            ).scalar_one()
        )

    insert_ready_media_for_reconstruction(
        engine,
        trip_id=str(trip["id"]),
        member_id=owner_member_id,
        filename="owner-story.jpg",
        captured_at=datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
        latitude=35.0,
        longitude=127.0,
        sha256="a" * 64,
    )
    insert_ready_media_for_reconstruction(
        engine,
        trip_id=str(trip["id"]),
        member_id=contributor_member_id,
        filename="contributor-story.jpg",
        captured_at=datetime(2026, 6, 1, 9, 15, tzinfo=UTC),
        latitude=35.001,
        longitude=127.001,
        sha256="b" * 64,
    )

    reconstructed = client.post(
        f"/trips/{trip['id']}/reconstruction-runs",
        headers={"x-csrf-token": csrf_owner},
    )
    assert reconstructed.status_code == 200

    shared_media = contributor_client.get(f"/trips/{trip['id']}/media")
    assert shared_media.status_code == 200
    assert {item["contributor"] for item in shared_media.json()["media"]} == {
        "Owner",
        "Story Contributor",
    }

    story = contributor_client.get(f"/trips/{trip['id']}/reconstruction")
    assert story.status_code == 200
    contributors = {
        item["contributor"]
        for day in story.json()["days"]
        for stop in day["stops"]
        for moment in stop["moments"]
        for item in moment["media"]
    }
    assert contributors == {"Owner", "Story Contributor"}

    projection = contributor_client.get(f"/trips/{trip['id']}/story-draft-projection")
    assert projection.status_code == 200
    assert projection.json()["latestRun"]["id"] == story.json()["latestRun"]["id"]
    assert projection.json()["reviewItems"] == []
    day_id = story.json()["days"][0]["id"]
    stop_id = story.json()["days"][0]["stops"][0]["id"]
    day_photos = contributor_client.get(f"/trips/{trip['id']}/story-day-photos/{day_id}")
    assert day_photos.status_code == 200
    assert len(day_photos.json()["stops"][0]["photos"]) == 2
    assert day_photos.json()["stops"][0]["photos"][0]["previewUrl"]
    stop_photos = contributor_client.get(f"/trips/{trip['id']}/story-stop-photos/{stop_id}")
    assert stop_photos.status_code == 200
    assert len(stop_photos.json()["stops"][0]["photos"]) == 2
    with engine.connect() as connection:
        projection_count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM story_draft_projections
                WHERE trip_id = CAST(:trip_id AS uuid)
                """
            ),
            {"trip_id": trip["id"]},
        ).scalar_one()
        day_projection_count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM story_day_photo_projections
                WHERE trip_id = CAST(:trip_id AS uuid)
                """
            ),
            {"trip_id": trip["id"]},
        ).scalar_one()
        stop_projection_count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM story_stop_photo_projections
                WHERE trip_id = CAST(:trip_id AS uuid)
                """
            ),
            {"trip_id": trip["id"]},
        ).scalar_one()
        grant_cache_count = connection.execute(
            text("SELECT count(*) FROM asset_download_grants")
        ).scalar_one()
    assert projection_count == 1
    assert day_projection_count == 1
    assert stop_projection_count == 1
    assert grant_cache_count >= 2

    other_client = TestClient(
        create_app(
            settings=Settings(DATABASE_URL=PostgresDsn(url), TRIPWEAVE_BLOB_DIR=tmp_path),
            engine=engine,
        )
    )
    register(other_client, "story-outsider@example.com", "Outsider")
    denied_projection = other_client.get(f"/trips/{trip['id']}/story-draft-projection")
    assert denied_projection.status_code == 404
    denied_day_photos = other_client.get(f"/trips/{trip['id']}/story-day-photos/{day_id}")
    assert denied_day_photos.status_code == 404

    cannot_reconstruct = contributor_client.post(
        f"/trips/{trip['id']}/reconstruction-runs",
        headers={"x-csrf-token": csrf_contributor},
    )
    assert cannot_reconstruct.status_code == 404

    cannot_edit = contributor_client.patch(
        f"/trips/{trip['id']}",
        headers={"x-csrf-token": csrf_contributor},
        json={"title": "Edited by contributor"},
    )
    assert cannot_edit.status_code == 404


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
        client.post(
            f"/invitations/{token}/accept",
            headers={"x-csrf-token": csrf_owner},
            json={},
        ).status_code
        == 404
    )


def test_action_rate_limits_cover_invites_uploads_and_publication(
    engine: Engine, tmp_path: Path
) -> None:
    url = get_test_database_url()
    assert url is not None
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    settings = Settings(
        DATABASE_URL=PostgresDsn(url),
        TRIPWEAVE_BLOB_DIR=tmp_path,
        TRIPWEAVE_AUTH_RATE_LIMIT_MAX_ATTEMPTS=100,
        TRIPWEAVE_ACTION_RATE_LIMIT_WINDOW_SECONDS=60,
        TRIPWEAVE_INVITATION_RATE_LIMIT_MAX_ATTEMPTS=1,
        TRIPWEAVE_UPLOAD_REGISTRATION_RATE_LIMIT_MAX_ATTEMPTS=1,
        TRIPWEAVE_PUBLICATION_RATE_LIMIT_MAX_ATTEMPTS=1,
    )
    with TestClient(create_app(settings=settings, engine=engine)) as limited_client:
        csrf_token = register(limited_client, "rate-limited-owner@example.com")
        trip = create_trip(limited_client, csrf_token)

        assert create_invitation(limited_client, csrf_token, trip["id"])["status"] == "pending"
        second_invite = limited_client.post(
            f"/trips/{trip['id']}/invitations",
            headers={"x-csrf-token": csrf_token},
            json={},
        )
        assert second_invite.status_code == 429

        first_upload = limited_client.post(
            f"/trips/{trip['id']}/upload-sessions",
            headers={"x-csrf-token": csrf_token},
            json={"files": [{"filename": "a.jpg", "byteSize": 1, "mimeType": "image/jpeg"}]},
        )
        assert first_upload.status_code == 201
        second_upload = limited_client.post(
            f"/trips/{trip['id']}/upload-sessions",
            headers={"x-csrf-token": csrf_token},
            json={"files": [{"filename": "b.jpg", "byteSize": 1, "mimeType": "image/jpeg"}]},
        )
        assert second_upload.status_code == 429

        first_publish = limited_client.post(
            f"/trips/{trip['id']}/publications",
            headers={"x-csrf-token": csrf_token},
        )
        assert first_publish.status_code == 409
        second_publish = limited_client.post(
            f"/trips/{trip['id']}/publications",
            headers={"x-csrf-token": csrf_token},
        )
        assert second_publish.status_code == 429
    command.downgrade(config, "base")


def test_contributor_cannot_access_other_trip_or_alter_other_contributor_media(
    client: TestClient, engine: Engine, tmp_path: Path
) -> None:
    url = get_test_database_url()
    assert url is not None
    csrf_owner = register(client, "multi-guest-owner@example.com")
    trip_one = create_trip(client, csrf_owner, "One")
    trip_two = create_trip(client, csrf_owner, "Two")

    contributor_one = TestClient(
        create_app(
            settings=Settings(DATABASE_URL=PostgresDsn(url), TRIPWEAVE_BLOB_DIR=tmp_path),
            engine=engine,
        )
    )
    contributor_two = TestClient(
        create_app(
            settings=Settings(DATABASE_URL=PostgresDsn(url), TRIPWEAVE_BLOB_DIR=tmp_path),
            engine=engine,
        )
    )
    invite_one = create_invitation(client, csrf_owner, trip_one["id"])
    invite_two = create_invitation(client, csrf_owner, trip_one["id"])
    csrf_contributor_one = register(contributor_one, "one@example.com", "One")
    csrf_contributor_two = register(contributor_two, "two@example.com", "Two")
    accept_invitation(
        contributor_one, token_from_invite_url(str(invite_one["inviteUrl"])), csrf_contributor_one
    )
    accept_invitation(
        contributor_two, token_from_invite_url(str(invite_two["inviteUrl"])), csrf_contributor_two
    )

    media_one = upload_completed_jpeg(
        contributor_one, csrf_contributor_one, trip_one["id"], jpeg_bytes()
    )
    media_two = upload_completed_jpeg(
        contributor_two,
        csrf_contributor_two,
        trip_one["id"],
        jpeg_bytes(),
        filename="two.jpg",
    )

    listed = contributor_one.get(f"/trips/{trip_one['id']}/media")
    assert listed.status_code == 200
    can_update_by_media_id = {
        item["id"]: item["canUpdateVisibility"] for item in listed.json()["media"]
    }
    assert can_update_by_media_id[media_one] is True
    assert can_update_by_media_id[media_two] is False

    assert contributor_one.get(f"/trips/{trip_two['id']}/media").status_code == 404
    denied = contributor_two.patch(
        f"/media/{media_one}",
        headers={"x-csrf-token": csrf_contributor_two},
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
    contributor_client = TestClient(
        create_app(
            settings=Settings(DATABASE_URL=PostgresDsn(url), TRIPWEAVE_BLOB_DIR=tmp_path),
            engine=engine,
        )
    )
    csrf_contributor = register(contributor_client, "removed@example.com", "Removed")
    accepted = accept_invitation(
        contributor_client, token_from_invite_url(str(invitation["inviteUrl"])), csrf_contributor
    )
    media_item_id = upload_completed_jpeg(
        contributor_client, csrf_contributor, trip["id"], jpeg_bytes()
    )
    member_id = accepted["id"]

    removed = client.delete(f"/trip-members/{member_id}", headers={"x-csrf-token": csrf_owner})
    assert removed.status_code == 204
    assert contributor_client.get(f"/trips/{trip['id']}/media").status_code == 404

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
        visibility, include_in_story = connection.execute(
            text("SELECT visibility, include_in_story FROM media_items WHERE id = :id"),
            {"id": media_item_id},
        ).one()

    assert media_count == 1
    assert job_count == 1
    assert job_type == "ingest_media"
    assert visibility == "story"
    assert include_in_story is True


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
    with engine.connect() as connection:
        original_ref = connection.execute(
            text(
                """
                SELECT original_store_alias, original_object_key
                FROM media_items
                WHERE id = :id
                """
            ),
            {"id": media_item_id},
        ).one()
    assert blob_store.exists(
        BlobRef(
            store_alias=original_ref.original_store_alias,
            object_key=original_ref.original_object_key,
        )
    )

    with session_factory() as db:
        job = claim_job(db, settings, "test-worker")
    assert job is not None
    handle_job(settings, session_factory, blob_store, ManualGeocoder(), "test-worker", job)

    with engine.connect() as connection:
        state = connection.execute(
            text(
                """
                SELECT processing_state, original_retention_state, original_deleted_at
                FROM media_items
                WHERE id = :id
                """
            ),
            {"id": media_item_id},
        ).one()
        asset_count = connection.execute(text("SELECT count(*) FROM media_assets")).scalar_one()
        job_state = connection.execute(text("SELECT state FROM processing_jobs")).scalar_one()

    assert state.processing_state == "ready"
    assert state.original_retention_state == "deleted"
    assert state.original_deleted_at is not None
    assert not blob_store.exists(
        BlobRef(
            store_alias=original_ref.original_store_alias,
            object_key=original_ref.original_object_key,
        )
    )
    assert asset_count == 2
    assert job_state == "succeeded"

    retry = client.post(f"/media/{media_item_id}/retry", headers={"x-csrf-token": csrf_token})
    assert retry.status_code == 409
    assert retry.json()["detail"] == "Original file is no longer retained"

    handle_job(
        settings,
        session_factory,
        blob_store,
        ManualGeocoder(),
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


def test_publication_creates_immutable_public_story_and_revokes_access(
    client: TestClient, engine: Engine
) -> None:
    csrf_token = register(client, "publisher@example.com")
    trip = create_trip(client, csrf_token, "Published Kyoto")
    trip_id = str(trip["id"])
    with engine.connect() as connection:
        member_id = str(
            connection.execute(
                text("SELECT id FROM trip_members WHERE trip_id = CAST(:trip_id AS uuid)"),
                {"trip_id": trip_id},
            ).scalar_one()
        )
    media_id = insert_ready_media_for_reconstruction(
        engine,
        trip_id=trip_id,
        member_id=member_id,
        filename="private-original-name.jpg",
        captured_at=datetime(2026, 7, 2, 16, 0, tzinfo=UTC),
        latitude=35.0,
        longitude=135.0,
        sha256="9" * 64,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE media_items
                SET visibility = 'story', include_in_story = true
                WHERE id = CAST(:media_id AS uuid)
                """
            ),
            {"media_id": media_id},
        )
    insert_sanitized_assets(client, engine, media_id)

    reconstructed = client.post(
        f"/trips/{trip_id}/reconstruction-runs",
        headers={"x-csrf-token": csrf_token},
    )
    assert reconstructed.status_code == 200
    reconstructed_body = reconstructed.json()
    assert reconstructed_body["days"]
    day_id = reconstructed_body["days"][0]["id"]
    stop_id = reconstructed_body["days"][0]["stops"][0]["id"]
    day_note = client.post(
        f"/trips/{trip_id}/edit-operations",
        headers={"x-csrf-token": csrf_token},
        json={
            "operationType": "set_day_note",
            "payload": {"dayId": day_id, "note": "Start with temple photos."},
        },
    )
    assert day_note.status_code == 200, day_note.text
    stop_note = client.post(
        f"/trips/{trip_id}/edit-operations",
        headers={"x-csrf-token": csrf_token},
        json={
            "operationType": "set_stop_note",
            "payload": {"stopId": stop_id, "note": "Golden hour by the river."},
        },
    )
    assert stop_note.status_code == 200, stop_note.text

    publication = client.post(
        f"/trips/{trip_id}/publications",
        headers={"x-csrf-token": csrf_token},
    )
    assert publication.status_code == 200
    share_link = publication.json()["shareLink"]
    link_id = share_link["id"]
    share_url = share_link["shareUrl"]
    assert isinstance(share_url, str)
    token = share_url.rsplit("/", 1)[-1]

    run_one_worker_job(client, engine)

    public_story = client.get(f"/public/shares/{token}")
    assert public_story.status_code == 200
    body = public_story.text
    assert "Published Kyoto" in body
    assert "media_private" not in body
    assert "sourceBlobRef" not in body
    assert "private-original-name.jpg" not in body
    assert "rawExif" not in body
    story_day = public_story.json()["story"]["days"][0]
    assert story_day["note"] == "Start with temple photos."
    assert story_day["stops"][0]["note"] == "Golden hour by the river."

    thumbnail_url = story_day["stops"][0]["moments"][0]["media"][0]["thumbnailUrl"]
    preview_url = story_day["stops"][0]["moments"][0]["media"][0]["previewUrl"]
    assert thumbnail_url.startswith("http://testserver/")
    assert preview_url.startswith("http://testserver/")
    asset_path = upload_path(thumbnail_url)
    public_asset = client.get(asset_path)
    assert public_asset.status_code == 200
    assert public_asset.content == b"thumbnail-webp"
    preview_asset = client.get(upload_path(preview_url))
    assert preview_asset.status_code == 200
    assert preview_asset.content == b"display-webp"

    second_publication = client.post(
        f"/trips/{trip_id}/publications",
        headers={"x-csrf-token": csrf_token},
    )
    assert second_publication.status_code == 200
    second_token = second_publication.json()["shareLink"]["shareUrl"].rsplit("/", 1)[-1]
    run_one_worker_job(client, engine)
    assert client.get(f"/public/shares/{second_token}").status_code == 200

    links = client.get(f"/trips/{trip_id}/publications")
    assert links.status_code == 200
    assert any(link["id"] == link_id for link in links.json()["shareLinks"])
    revoked = client.delete(f"/share-links/{link_id}", headers={"x-csrf-token": csrf_token})
    assert revoked.status_code == 204
    assert client.get(f"/public/shares/{token}").status_code == 404


def test_publication_requires_story_visible_media(client: TestClient, engine: Engine) -> None:
    csrf_token = register(client, "not-ready-publisher@example.com")
    trip = create_trip(client, csrf_token, "Private Kyoto")
    trip_id = str(trip["id"])
    with engine.connect() as connection:
        member_id = str(
            connection.execute(
                text("SELECT id FROM trip_members WHERE trip_id = CAST(:trip_id AS uuid)"),
                {"trip_id": trip_id},
            ).scalar_one()
        )
    media_id = insert_ready_media_for_reconstruction(
        engine,
        trip_id=trip_id,
        member_id=member_id,
        filename="private.jpg",
        captured_at=datetime(2026, 7, 2, 16, 0, tzinfo=UTC),
        latitude=35.0,
        longitude=135.0,
        sha256="8" * 64,
    )
    insert_sanitized_assets(client, engine, media_id)
    reconstructed = client.post(
        f"/trips/{trip_id}/reconstruction-runs",
        headers={"x-csrf-token": csrf_token},
    )
    assert reconstructed.status_code == 200

    publication = client.post(
        f"/trips/{trip_id}/publications",
        headers={"x-csrf-token": csrf_token},
    )

    assert publication.status_code == 409
    assert (
        publication.json()["detail"]
        == "Mark at least one ready media item as Story before publishing"
    )
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM share_links")).scalar_one() == 0


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


def test_review_edit_operations_authorization_undo_and_rerun(
    client: TestClient, engine: Engine
) -> None:
    csrf_token = register(client, "review-owner@example.com")
    trip = create_trip(client, csrf_token, "Review Trip")
    trip_id = str(trip["id"])
    with engine.connect() as connection:
        member_id = str(
            connection.execute(
                text(
                    """
                    SELECT id FROM trip_members
                    WHERE trip_id = CAST(:trip_id AS uuid) AND role = 'owner'
                    """
                ),
                {"trip_id": trip_id},
            ).scalar_one()
        )

    media_specs = [
        (1, datetime(2026, 6, 8, 1, 0, tzinfo=UTC), 35.0, 127.0),
        (2, datetime(2026, 6, 8, 1, 20, tzinfo=UTC), 35.0, 127.0),
        (3, datetime(2026, 6, 8, 3, 0, tzinfo=UTC), 35.01, 127.01),
        (4, datetime(2026, 6, 8, 3, 20, tzinfo=UTC), 35.01, 127.01),
        (5, datetime(2026, 6, 8, 6, 0, tzinfo=UTC), 35.03, 127.03),
        (6, None, 35.04, 127.04),
    ]
    media_ids = [
        insert_ready_media_for_reconstruction(
            engine,
            trip_id=trip_id,
            member_id=member_id,
            filename=f"review-{index}.jpg",
            captured_at=captured_at,
            latitude=latitude,
            longitude=longitude,
            sha256=str(index) * 64,
        )
        for index, captured_at, latitude, longitude in media_specs
    ]

    reconstructed = client.post(
        f"/trips/{trip_id}/reconstruction-runs", headers={"x-csrf-token": csrf_token}
    )
    assert reconstructed.status_code == 200
    body = reconstructed.json()
    day_id = body["days"][0]["id"]
    stops = body["days"][0]["stops"]
    assert len(stops) >= 3
    assert body["days"][0]["legs"][0]["routeSource"] == "photo_inferred"
    assert body["days"][0]["legs"][0]["geometry"]["type"] == "LineString"
    stop_one, stop_two, stop_three = stops[:3]
    assert stop_one["latitude"] == 35.0
    assert stop_one["longitude"] == 127.0
    moment_one, moment_two = stop_one["moments"][:2]
    assert moment_one["media"][0]["latitude"] == 35.0
    assert moment_one["media"][0]["contributor"] == "Owner"
    stop_two_moment_one, stop_two_moment_two = stop_two["moments"][:2]
    review_item_id = body["reviewItems"][0]["id"]

    with engine.connect() as connection:
        route_id = str(connection.execute(text("SELECT id FROM trip_legs LIMIT 1")).scalar_one())
        stale_updated_at = connection.execute(
            text("SELECT updated_at FROM stops WHERE id = CAST(:id AS uuid)"),
            {"id": stop_three["id"]},
        ).scalar_one()

    stale = client.post(
        f"/trips/{trip_id}/edit-operations",
        headers={"x-csrf-token": csrf_token},
        json={
            "operationType": "rename_stop",
            "expectedUpdatedAt": stale_updated_at.isoformat(),
            "payload": {"stopId": stop_three["id"], "title": "First edit"},
        },
    )
    assert stale.status_code == 200
    stale_again = client.post(
        f"/trips/{trip_id}/edit-operations",
        headers={"x-csrf-token": csrf_token},
        json={
            "operationType": "rename_stop",
            "expectedUpdatedAt": stale_updated_at.isoformat(),
            "payload": {"stopId": stop_three["id"], "title": "Stale edit"},
        },
    )
    assert stale_again.status_code == 409

    operations = [
        ("move_media", {"mediaItemId": media_ids[0], "momentId": moment_two["id"]}),
        ("move_after_midnight_media", {"mediaItemId": media_ids[0], "direction": "previous"}),
        ("rename_day", {"dayId": day_id, "title": "Arrival day"}),
        ("rename_stop", {"stopId": stop_one["id"], "title": "Harbor"}),
        ("set_day_note", {"dayId": day_id, "note": "Meet at the ferry before lunch."}),
        ("set_stop_note", {"stopId": stop_one["id"], "note": "Best photos are near the pier."}),
        ("rename_moment", {"momentId": moment_one["id"], "title": "First look"}),
        ("move_stop_on_map", {"stopId": stop_one["id"], "latitude": 35.001, "longitude": 127.001}),
        ("change_route_mode", {"tripLegId": route_id, "routeSource": "manual"}),
        ("exclude_media_from_story", {"mediaItemId": media_ids[1]}),
        ("lock_record", {"targetType": "stop", "targetId": stop_one["id"]}),
        ("split_stop", {"stopId": stop_two["id"], "afterMomentId": stop_two_moment_one["id"]}),
        (
            "merge_moments",
            {
                "sourceMomentId": stop_two_moment_two["id"],
                "targetMomentId": stop_two_moment_one["id"],
            },
        ),
        ("merge_stops", {"sourceStopId": stop_three["id"], "targetStopId": stop_one["id"]}),
        ("resolve_review_item", {"reviewItemId": review_item_id, "resolution": "Fixed"}),
        ("dismiss_review_item", {"reviewItemId": review_item_id, "resolution": "Not relevant"}),
    ]
    for operation_type, payload in operations:
        response = client.post(
            f"/trips/{trip_id}/edit-operations",
            headers={"x-csrf-token": csrf_token},
            json={"operationType": operation_type, "payload": payload},
        )
        assert response.status_code == 200, response.text
        assert response.json()["operationType"] == operation_type

    with engine.connect() as connection:
        before_invalid = connection.execute(
            text("SELECT COUNT(*) FROM edit_operations")
        ).scalar_one()
    invalid = client.post(
        f"/trips/{trip_id}/edit-operations",
        headers={"x-csrf-token": csrf_token},
        json={"operationType": "merge_stops", "payload": {"sourceStopId": stop_one["id"]}},
    )
    assert invalid.status_code == 422
    with engine.connect() as connection:
        after_invalid = connection.execute(
            text("SELECT COUNT(*) FROM edit_operations")
        ).scalar_one()
    assert after_invalid == before_invalid

    undo = client.post(
        f"/trips/{trip_id}/edit-operations/undo", headers={"x-csrf-token": csrf_token}
    )
    assert undo.status_code == 200
    assert undo.json()["status"] == "applied"

    rerun = client.post(
        f"/trips/{trip_id}/reconstruction-runs", headers={"x-csrf-token": csrf_token}
    )
    assert rerun.status_code == 200
    rerun_days = rerun.json()["days"]
    assert any(day.get("title") == "Arrival day" for day in rerun_days)
    assert any(day.get("note") == "Meet at the ferry before lunch." for day in rerun_days)
    assert any(
        stop.get("note") == "Best photos are near the pier."
        for day in rerun_days
        for stop in day["stops"]
    )

    other_csrf = register(client, "review-other@example.com")
    denied = client.post(
        f"/trips/{trip_id}/edit-operations",
        headers={"x-csrf-token": other_csrf},
        json={
            "operationType": "rename_day",
            "payload": {"dayId": day_id, "title": "Denied"},
        },
    )
    assert denied.status_code == 404


def test_merge_adjacent_stops_rewires_trip_legs(client: TestClient, engine: Engine) -> None:
    csrf_token = register(client, "merge-route-owner@example.com")
    trip = create_trip(client, csrf_token, "Merge Route Trip")
    trip_id = str(trip["id"])
    with engine.connect() as connection:
        member_id = str(
            connection.execute(
                text(
                    """
                    SELECT id FROM trip_members
                    WHERE trip_id = CAST(:trip_id AS uuid) AND role = 'owner'
                    """
                ),
                {"trip_id": trip_id},
            ).scalar_one()
        )

    for index, captured_at, latitude, longitude in [
        (1, datetime(2026, 6, 8, 1, 0, tzinfo=UTC), 35.0, 127.0),
        (2, datetime(2026, 6, 8, 3, 0, tzinfo=UTC), 35.01, 127.01),
        (3, datetime(2026, 6, 8, 6, 0, tzinfo=UTC), 35.03, 127.03),
    ]:
        insert_ready_media_for_reconstruction(
            engine,
            trip_id=trip_id,
            member_id=member_id,
            filename=f"merge-route-{index}.jpg",
            captured_at=captured_at,
            latitude=latitude,
            longitude=longitude,
            sha256=f"{index:064d}",
        )

    reconstructed = client.post(
        f"/trips/{trip_id}/reconstruction-runs", headers={"x-csrf-token": csrf_token}
    )
    assert reconstructed.status_code == 200
    stops = reconstructed.json()["days"][0]["stops"]
    assert len(stops) == 3
    stop_one, stop_two, stop_three = stops
    rename = client.post(
        f"/trips/{trip_id}/edit-operations",
        headers={"x-csrf-token": csrf_token},
        json={
            "operationType": "rename_stop",
            "payload": {"stopId": stop_one["id"], "title": "Named target stop"},
        },
    )
    assert rename.status_code == 200, rename.text
    rename_source = client.post(
        f"/trips/{trip_id}/edit-operations",
        headers={"x-csrf-token": csrf_token},
        json={
            "operationType": "rename_stop",
            "payload": {"stopId": stop_two["id"], "title": "Named source stop"},
        },
    )
    assert rename_source.status_code == 200, rename_source.text

    merge = client.post(
        f"/trips/{trip_id}/edit-operations",
        headers={"x-csrf-token": csrf_token},
        json={
            "operationType": "merge_stops",
            "payload": {"sourceStopId": stop_two["id"], "targetStopId": stop_one["id"]},
        },
    )
    assert merge.status_code == 200, merge.text

    refreshed = client.get(f"/trips/{trip_id}/reconstruction", headers={"x-csrf-token": csrf_token})
    assert refreshed.status_code == 200
    merged_stops = refreshed.json()["days"][0]["stops"]
    assert [stop["id"] for stop in merged_stops] == [stop_one["id"], stop_three["id"]]
    assert merged_stops[0]["title"] == "Named target stop"

    with engine.connect() as connection:
        leg_rows = connection.execute(
            text(
                """
                SELECT from_stop_id::text, to_stop_id::text, ST_AsText(geometry::geometry)
                FROM trip_legs
                WHERE trip_id = CAST(:trip_id AS uuid)
                ORDER BY created_at, id
                """
            ),
            {"trip_id": trip_id},
        ).all()
    legs = [
        (str(from_stop_id), str(to_stop_id), str(geometry))
        for from_stop_id, to_stop_id, geometry in leg_rows
    ]

    assert legs == [(stop_one["id"], stop_three["id"], "LINESTRING(127.005 35.005,127.03 35.03)")]
    assert all(
        stop_two["id"] not in (from_stop_id, to_stop_id) for from_stop_id, to_stop_id, _ in legs
    )


def test_group_route_displays_forked_stop_labels_and_trace_edges(
    client: TestClient, engine: Engine
) -> None:
    csrf_token = register(client, "fork-route-owner@example.com")
    trip = create_trip(client, csrf_token, "Fork Route Trip")
    trip_id = str(trip["id"])
    with engine.begin() as connection:
        owner_member_id = str(
            connection.execute(
                text(
                    """
                    SELECT id FROM trip_members
                    WHERE trip_id = CAST(:trip_id AS uuid) AND role = 'owner'
                    """
                ),
                {"trip_id": trip_id},
            ).scalar_one()
        )
        guest_member_id = str(
            connection.execute(
                text(
                    """
                    INSERT INTO trip_members (trip_id, role, display_name)
                    VALUES (CAST(:trip_id AS uuid), 'contributor', 'Guest')
                    RETURNING id
                    """
                ),
                {"trip_id": trip_id},
            ).scalar_one()
        )

    media_rows = [
        (
            owner_member_id,
            "owner-shared-start.jpg",
            datetime(2026, 6, 8, 1, 0, tzinfo=UTC),
            35.0,
            127.0,
            "1",
        ),
        (
            guest_member_id,
            "guest-shared-start.jpg",
            datetime(2026, 6, 8, 1, 5, tzinfo=UTC),
            35.0001,
            127.0001,
            "2",
        ),
        (
            owner_member_id,
            "owner-branch.jpg",
            datetime(2026, 6, 8, 2, 0, tzinfo=UTC),
            35.01,
            127.01,
            "3",
        ),
        (
            guest_member_id,
            "guest-branch.jpg",
            datetime(2026, 6, 8, 2, 2, tzinfo=UTC),
            35.02,
            127.02,
            "4",
        ),
        (
            owner_member_id,
            "owner-shared-end.jpg",
            datetime(2026, 6, 8, 3, 0, tzinfo=UTC),
            35.03,
            127.03,
            "5",
        ),
        (
            guest_member_id,
            "guest-shared-end.jpg",
            datetime(2026, 6, 8, 3, 4, tzinfo=UTC),
            35.0301,
            127.0301,
            "6",
        ),
    ]
    for member_id, filename, captured_at, latitude, longitude, suffix in media_rows:
        insert_ready_media_for_reconstruction(
            engine,
            trip_id=trip_id,
            member_id=member_id,
            filename=filename,
            captured_at=captured_at,
            latitude=latitude,
            longitude=longitude,
            sha256=suffix.zfill(64),
        )

    reconstructed = client.post(
        f"/trips/{trip_id}/reconstruction-runs", headers={"x-csrf-token": csrf_token}
    )

    assert reconstructed.status_code == 200, reconstructed.text
    day = reconstructed.json()["days"][0]
    stops = day["stops"]
    assert [stop["displayPosition"] for stop in stops] == ["1", "2a", "2b", "3"]
    assert [stop["contributorCount"] for stop in stops] == [2, 1, 1, 2]

    edge_labels = {
        (
            next(stop["displayPosition"] for stop in stops if stop["id"] == leg["fromStopId"]),
            next(stop["displayPosition"] for stop in stops if stop["id"] == leg["toStopId"]),
        )
        for leg in day["legs"]
    }
    assert edge_labels == {("1", "2a"), ("1", "2b"), ("2a", "3"), ("2b", "3")}
    assert all(leg["isForked"] for leg in day["legs"])


def test_split_stop_reorders_stops_and_rewires_trip_legs(
    client: TestClient, engine: Engine
) -> None:
    csrf_token = register(client, "split-route-owner@example.com")
    trip = create_trip(client, csrf_token, "Split Route Trip")
    trip_id = str(trip["id"])
    with engine.connect() as connection:
        member_id = str(
            connection.execute(
                text(
                    """
                    SELECT id FROM trip_members
                    WHERE trip_id = CAST(:trip_id AS uuid) AND role = 'owner'
                    """
                ),
                {"trip_id": trip_id},
            ).scalar_one()
        )

    for index, captured_at, latitude, longitude in [
        (1, datetime(2026, 6, 8, 1, 0, tzinfo=UTC), 35.0, 127.0),
        (2, datetime(2026, 6, 8, 1, 20, tzinfo=UTC), 35.0, 127.0),
        (3, datetime(2026, 6, 8, 3, 0, tzinfo=UTC), 35.01, 127.01),
    ]:
        insert_ready_media_for_reconstruction(
            engine,
            trip_id=trip_id,
            member_id=member_id,
            filename=f"split-route-{index}.jpg",
            captured_at=captured_at,
            latitude=latitude,
            longitude=longitude,
            sha256=f"{index:064d}",
        )

    reconstructed = client.post(
        f"/trips/{trip_id}/reconstruction-runs", headers={"x-csrf-token": csrf_token}
    )
    assert reconstructed.status_code == 200
    stops = reconstructed.json()["days"][0]["stops"]
    assert len(stops) == 2
    source_stop, next_stop = stops
    assert len(source_stop["moments"]) == 2
    split_after_moment_id = source_stop["moments"][0]["id"]
    rename = client.post(
        f"/trips/{trip_id}/edit-operations",
        headers={"x-csrf-token": csrf_token},
        json={
            "operationType": "rename_stop",
            "payload": {"stopId": source_stop["id"], "title": "Named split stop"},
        },
    )
    assert rename.status_code == 200, rename.text

    split = client.post(
        f"/trips/{trip_id}/edit-operations",
        headers={"x-csrf-token": csrf_token},
        json={
            "operationType": "split_stop",
            "payload": {"stopId": source_stop["id"], "afterMomentId": split_after_moment_id},
        },
    )
    assert split.status_code == 200, split.text
    new_stop_id = split.json()["afterValues"]["newStopId"]

    refreshed = client.get(f"/trips/{trip_id}/reconstruction", headers={"x-csrf-token": csrf_token})
    assert refreshed.status_code == 200
    split_stops = refreshed.json()["days"][0]["stops"]
    assert [stop["position"] for stop in split_stops] == [1, 2, 3]
    assert [stop["id"] for stop in split_stops] == [source_stop["id"], new_stop_id, next_stop["id"]]
    assert [stop["title"] for stop in split_stops[:2]] == [
        "Named split stop 1",
        "Named split stop 2",
    ]
    assert split_stops[0]["mediaCount"] == 1
    assert split_stops[1]["mediaCount"] == 1

    with engine.connect() as connection:
        legs = connection.execute(
            text(
                """
                SELECT from_stop_id::text, to_stop_id::text
                FROM trip_legs
                WHERE trip_id = CAST(:trip_id AS uuid)
                """
            ),
            {"trip_id": trip_id},
        ).all()

    assert (source_stop["id"], new_stop_id) in legs
    assert (new_stop_id, next_stop["id"]) in legs
    assert len(legs) == 2
    assert (source_stop["id"], next_stop["id"]) not in legs


def test_similarity_groups_and_clock_offset_suggestion_workflow(
    client: TestClient, engine: Engine
) -> None:
    csrf_token = register(client, "collab-owner@example.com")
    trip = create_trip(client, csrf_token, "Collaboration Trip")
    trip_id = str(trip["id"])
    with engine.begin() as connection:
        owner_member_id = str(
            connection.execute(
                text(
                    """
                    SELECT id FROM trip_members
                    WHERE trip_id = CAST(:trip_id AS uuid) AND role = 'owner'
                    """
                ),
                {"trip_id": trip_id},
            ).scalar_one()
        )
        contributor_member_id = str(
            connection.execute(
                text(
                    """
                    INSERT INTO trip_members (trip_id, role, display_name)
                    VALUES (CAST(:trip_id AS uuid), 'contributor', 'Guest')
                    RETURNING id
                    """
                ),
                {"trip_id": trip_id},
            ).scalar_one()
        )

    owner_device = insert_capture_device(
        engine,
        trip_id=trip_id,
        member_id=owner_member_id,
        device_key="owner-camera",
        display_name="Owner Camera",
    )
    guest_device = insert_capture_device(
        engine,
        trip_id=trip_id,
        member_id=contributor_member_id,
        device_key="guest-camera",
        display_name="Guest Camera",
    )
    base = datetime(2026, 6, 8, 1, 0, tzinfo=UTC)

    duplicate_one = insert_ready_media_for_reconstruction(
        engine,
        trip_id=trip_id,
        member_id=owner_member_id,
        filename="duplicate-a.jpg",
        captured_at=base,
        latitude=35.0,
        longitude=127.0,
        sha256="a" * 64,
        perceptual_hash="ff00ff00ff00ff00",
        capture_device_id=owner_device,
    )
    duplicate_two = insert_ready_media_for_reconstruction(
        engine,
        trip_id=trip_id,
        member_id=contributor_member_id,
        filename="duplicate-b.jpg",
        captured_at=base + timedelta(minutes=1),
        latitude=35.0,
        longitude=127.0,
        sha256="a" * 64,
        perceptual_hash="ff00ff00ff00ff00",
        capture_device_id=guest_device,
    )
    similar_scene = insert_ready_media_for_reconstruction(
        engine,
        trip_id=trip_id,
        member_id=owner_member_id,
        filename="similar-scene-a.jpg",
        captured_at=base + timedelta(minutes=10),
        latitude=35.001,
        longitude=127.001,
        sha256="b" * 64,
        perceptual_hash="0f0f0f0f0f0f0f0f",
        capture_device_id=owner_device,
    )
    insert_ready_media_for_reconstruction(
        engine,
        trip_id=trip_id,
        member_id=contributor_member_id,
        filename="similar-scene-b.jpg",
        captured_at=base + timedelta(minutes=12),
        latitude=35.001,
        longitude=127.001,
        sha256="c" * 64,
        perceptual_hash="0f0f0f0f0f0f0f00",
        capture_device_id=guest_device,
    )
    for index in range(3):
        insert_ready_media_for_reconstruction(
            engine,
            trip_id=trip_id,
            member_id=owner_member_id,
            filename=f"clock-reference-{index}.jpg",
            captured_at=base + timedelta(hours=2, minutes=index * 5),
            latitude=35.01 + index * 0.0001,
            longitude=127.01,
            sha256=f"{index + 1}" * 64,
            perceptual_hash=f"1234567890abcd{index}{index}",
            capture_device_id=owner_device,
        )
        insert_ready_media_for_reconstruction(
            engine,
            trip_id=trip_id,
            member_id=contributor_member_id,
            filename=f"clock-behind-{index}.jpg",
            captured_at=base + timedelta(hours=1, minutes=index * 5),
            latitude=35.01 + index * 0.0001,
            longitude=127.01,
            sha256=f"{index + 4}" * 64,
            perceptual_hash=f"1234567890abcd{index}{index}",
            capture_device_id=guest_device,
        )

    reconstructed = client.post(
        f"/trips/{trip_id}/reconstruction-runs", headers={"x-csrf-token": csrf_token}
    )
    assert reconstructed.status_code == 200, reconstructed.text
    body = reconstructed.json()
    assert body["latestRun"]["summary"]["similarityGroups"] >= 2
    clock_review = next(
        item
        for item in body["reviewItems"]
        if item["itemType"] == "possible_clock_offset"
        and item["payload"]["captureDeviceId"] == guest_device
    )
    assert clock_review["payload"]["supportCount"] >= 3

    media_response = client.get(f"/trips/{trip_id}/media")
    assert media_response.status_code == 200
    media_by_id = {item["id"]: item for item in media_response.json()["media"]}
    assert media_by_id[duplicate_one]["similarityGroupCount"] == 2
    assert media_by_id[duplicate_two]["similarityGroupCount"] == 2

    groups_response = client.get(f"/trips/{trip_id}/similarity-groups")
    assert groups_response.status_code == 200
    group = next(
        group
        for group in groups_response.json()["groups"]
        if any(member["mediaItemId"] == similar_scene for member in group["members"])
    )
    new_representative = next(
        member["mediaItemId"]
        for member in group["members"]
        if member["mediaItemId"] != group["representativeMediaItemId"]
    )
    rep_response = client.post(
        f"/trips/{trip_id}/edit-operations",
        headers={"x-csrf-token": csrf_token},
        json={
            "operationType": "set_similarity_representative",
            "payload": {
                "similarityGroupId": group["id"],
                "mediaItemId": new_representative,
            },
        },
    )
    assert rep_response.status_code == 200, rep_response.text

    suggestion_id = clock_review["payload"]["suggestionId"]
    accept_response = client.post(
        f"/trips/{trip_id}/edit-operations",
        headers={"x-csrf-token": csrf_token},
        json={
            "operationType": "accept_clock_offset_suggestion",
            "reviewItemId": clock_review["id"],
            "payload": {"suggestionId": suggestion_id},
        },
    )
    assert accept_response.status_code == 200, accept_response.text
    assert len(accept_response.json()["afterValues"]["affectedMediaItemIds"]) >= 3
    with engine.connect() as connection:
        changed = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM media_items
                WHERE capture_device_id = CAST(:device_id AS uuid)
                  AND effective_captured_at_utc = original_captured_at_utc
                      + interval '1 second' * (
                          SELECT offset_seconds
                          FROM device_clock_offset_suggestions
                          WHERE id = CAST(:suggestion_id AS uuid)
                      )
                """
            ),
            {"device_id": guest_device, "suggestion_id": suggestion_id},
        ).scalar_one()
        original_unchanged = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM media_items
                WHERE capture_device_id = CAST(:device_id AS uuid)
                  AND original_captured_at_utc IS NOT NULL
                """
            ),
            {"device_id": guest_device},
        ).scalar_one()
        queued = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM processing_jobs
                WHERE job_type = 'reconstruct_trip'
                  AND target_id = CAST(:trip_id AS uuid)
                  AND state = 'pending'
                """
            ),
            {"trip_id": trip_id},
        ).scalar_one()
    assert changed == original_unchanged
    assert queued == 1
