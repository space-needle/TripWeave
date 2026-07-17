import os
from collections.abc import Iterator
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from tests import factories
from tripweave.adapters import orm
from tripweave.adapters.manual_geocoder import ManualGeocoder
from tripweave.adapters.reconstruction import reconstruct_trip
from tripweave.config import get_settings


def get_test_database_url() -> str | None:
    return os.environ.get("TRIPWEAVE_TEST_DATABASE_URL")


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    url = get_test_database_url()
    if not url:
        pytest.skip("TRIPWEAVE_TEST_DATABASE_URL is not set")

    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def migrated_database(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    url = get_test_database_url()
    assert url is not None
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()

    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    try:
        yield engine
    finally:
        command.downgrade(config, "base")
        get_settings.cache_clear()


def test_alembic_upgrade_downgrade_and_reupgrade(migrated_database: Engine) -> None:
    url = get_test_database_url()
    assert url is not None

    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    command.downgrade(config, "0001_enable_postgis")
    command.upgrade(config, "head")

    with migrated_database.connect() as connection:
        tables = {
            row.tablename
            for row in connection.execute(
                text(
                    """
                    SELECT tablename
                    FROM pg_tables
                    WHERE schemaname = 'public'
                    """
                )
            )
        }

    assert "media_items" in tables
    assert "processing_jobs" in tables
    assert "reconstruction_runs" in tables
    assert "trip_days" in tables
    assert "review_items" in tables
    assert "edit_operations" in tables


def test_database_constraints_reject_invalid_state_and_ownership(
    migrated_database: Engine,
) -> None:
    user = factories.user_row()
    other_user = factories.user_row(email="other@example.com")
    trip = factories.trip_row(created_by=cast(UUID, user["id"]))
    other_trip = factories.trip_row(created_by=cast(UUID, other_user["id"]))
    member = factories.member_row(trip_id=cast(UUID, trip["id"]), user_id=cast(UUID, user["id"]))

    with migrated_database.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO users (id, email, password_hash, display_name)
                VALUES (:id, :email, :password_hash, :display_name)
                """
            ),
            [user, other_user],
        )
        connection.execute(
            text(
                """
                INSERT INTO trips (id, title, timezone_id, created_by)
                VALUES (:id, :title, :timezone_id, :created_by)
                """
            ),
            [trip, other_trip],
        )
        connection.execute(
            text(
                """
                INSERT INTO trip_members (id, trip_id, user_id, role, display_name)
                VALUES (:id, :trip_id, :user_id, :role, :display_name)
                """
            ),
            member,
        )

    with pytest.raises(IntegrityError), migrated_database.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO upload_sessions (trip_id, member_id, state)
                VALUES (:trip_id, :member_id, 'registered')
                """
            ),
            {"trip_id": other_trip["id"], "member_id": member["id"]},
        )

    with pytest.raises(IntegrityError), migrated_database.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO processing_jobs (
                    job_type, target_type, target_id, state, idempotency_key
                )
                VALUES (
                    'metadata_extraction', 'media_item', :target_id,
                    'mysterious', :idempotency_key
                )
                """
            ),
            {"target_id": member["id"], "idempotency_key": "bad-state"},
        )


def insert_media(
    connection: Connection,
    *,
    trip_id: UUID,
    member_id: UUID,
    filename: str,
    captured_at: str | None,
    latitude: float | None,
    longitude: float | None,
    sha256: str,
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO media_items (
                trip_id, contributor_member_id, media_type, original_filename,
                declared_mime_type, byte_size, original_store_alias,
                original_object_key, original_captured_at_utc,
                original_utc_offset_minutes, effective_captured_at_utc,
                effective_location, time_source, location_source,
                time_confidence, location_confidence, sha256,
                processing_state, visibility
            )
            VALUES (
                :trip_id, :member_id, 'photo', :filename,
                'image/jpeg', 100, 'media_private',
                :object_key, CAST(:captured_at AS timestamptz), -420,
                CAST(:captured_at AS timestamptz),
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
                'original_metadata',
                CASE
                    WHEN CAST(:latitude AS double precision) IS NULL
                    THEN 'unknown'
                    ELSE 'original_metadata'
                END,
                CASE WHEN CAST(:captured_at AS timestamptz) IS NULL THEN NULL ELSE 1.0 END,
                CASE WHEN CAST(:latitude AS double precision) IS NULL THEN NULL ELSE 1.0 END,
                :sha256, 'ready', 'trip'
            )
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
        },
    )


def test_reconstruction_creates_days_stops_moments_reviews_and_preserves_locked(
    migrated_database: Engine,
) -> None:
    owner = factories.user_row(email="owner-recon@example.com")
    contributor = factories.user_row(email="guest-recon@example.com")
    trip = factories.trip_row(created_by=cast(UUID, owner["id"]))
    owner_member = factories.member_row(
        trip_id=cast(UUID, trip["id"]), user_id=cast(UUID, owner["id"])
    )
    owner_member["role"] = "owner"
    contributor_member = factories.member_row(
        trip_id=cast(UUID, trip["id"]), user_id=cast(UUID, contributor["id"])
    )
    contributor_member["display_name"] = "Guest"

    with migrated_database.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO users (id, email, password_hash, display_name)
                VALUES (:id, :email, :password_hash, :display_name)
                """
            ),
            [owner, contributor],
        )
        connection.execute(
            text(
                """
                INSERT INTO trips (id, title, timezone_id, day_cutoff_hour, created_by)
                VALUES (:id, :title, :timezone_id, 4, :created_by)
                """
            ),
            trip,
        )
        connection.execute(
            text(
                """
                INSERT INTO trip_members (id, trip_id, user_id, role, display_name)
                VALUES (:id, :trip_id, :user_id, :role, :display_name)
                """
            ),
            [owner_member, contributor_member],
        )
        media_rows = [
            ("d1-owner.jpg", "2026-07-02T16:00:00+00:00", 37.0000, -122.0000, "a" * 64),
            ("d1-guest.jpg", "2026-07-02T16:05:00+00:00", 37.0001, -122.0001, "b" * 64),
            ("d1-missing-bracket.jpg", "2026-07-02T16:07:00+00:00", None, None, "c" * 64),
            ("d1-bracket-after.jpg", "2026-07-02T16:10:00+00:00", 37.0001, -122.0001, "d" * 64),
            ("d1-owner-again.jpg", "2026-07-02T18:30:00+00:00", 37.0000, -122.0000, "e" * 64),
            ("parallel.jpg", "2026-07-02T18:35:00+00:00", 37.0200, -122.0200, "f" * 64),
            ("ambiguous.jpg", "2026-07-02T22:00:00+00:00", None, None, "1" * 64),
            ("d2.jpg", "2026-07-03T18:00:00+00:00", 37.4000, -122.4000, "2" * 64),
            ("no-time.jpg", None, 37.4000, -122.4000, "3" * 64),
        ]
        for index, (filename, captured_at, latitude, longitude, sha256) in enumerate(media_rows):
            insert_media(
                connection,
                trip_id=cast(UUID, trip["id"]),
                member_id=cast(
                    UUID,
                    contributor_member["id"] if index in {1, 5} else owner_member["id"],
                ),
                filename=filename,
                captured_at=captured_at,
                latitude=latitude,
                longitude=longitude,
                sha256=sha256,
            )

    with Session(migrated_database) as session:
        db_trip = session.get(orm.Trip, trip["id"])
        assert db_trip is not None
        summary = reconstruct_trip(db=session, trip=db_trip, geocoder=ManualGeocoder())
        assert summary.days == 2
        assert summary.stops >= 4
        assert summary.moments >= 4
        assert summary.review_items == 2

        shared_moments = session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT moment_id
                    FROM moment_participants
                    GROUP BY moment_id
                    HAVING COUNT(*) > 1
                ) shared
                """
            )
        ).scalar_one()
        assert shared_moments == 1

        assert session.execute(text("SELECT COUNT(*) FROM trip_legs")).scalar_one() >= 1
        assert (
            session.execute(
                text("SELECT COUNT(*) FROM trip_legs WHERE route_source = 'photo_inferred'")
            ).scalar_one()
            >= 1
        )

        locked_place_id = session.execute(text("SELECT id FROM places LIMIT 1")).scalar_one()
        session.execute(
            text("UPDATE places SET user_locked = true WHERE id = :id"),
            {"id": locked_place_id},
        )
        session.commit()

        second = reconstruct_trip(db=session, trip=db_trip, geocoder=ManualGeocoder())
        assert second.days == summary.days
        assert second.review_items == summary.review_items
        preserved = session.execute(
            text("SELECT COUNT(*) FROM places WHERE id = :id AND user_locked = true"),
            {"id": locked_place_id},
        ).scalar_one()
        assert preserved == 1


def test_incremental_reconstruction_adds_new_media_without_replacing_story(
    migrated_database: Engine,
) -> None:
    user = factories.user_row(email="owner-incremental@example.com")
    trip = factories.trip_row(
        created_by=cast(UUID, user["id"]),
        timezone_id="America/Los_Angeles",
    )
    owner_member = factories.member_row(
        trip_id=cast(UUID, trip["id"]), user_id=cast(UUID, user["id"])
    )
    owner_member["role"] = "owner"
    with migrated_database.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO users (id, email, password_hash, display_name)
                VALUES (:id, :email, :password_hash, :display_name)
                """
            ),
            user,
        )
        connection.execute(
            text(
                """
                INSERT INTO trips (id, title, timezone_id, created_by)
                VALUES (:id, :title, :timezone_id, :created_by)
                """
            ),
            trip,
        )
        connection.execute(
            text(
                """
                INSERT INTO trip_members (id, trip_id, user_id, role, display_name)
                VALUES (:id, :trip_id, :user_id, :role, :display_name)
                """
            ),
            owner_member,
        )
        insert_media(
            connection,
            trip_id=cast(UUID, trip["id"]),
            member_id=cast(UUID, owner_member["id"]),
            filename="first-stop.jpg",
            captured_at="2026-07-02T16:00:00+00:00",
            latitude=37.0000,
            longitude=-122.0000,
            sha256="4" * 64,
        )
        insert_media(
            connection,
            trip_id=cast(UUID, trip["id"]),
            member_id=cast(UUID, owner_member["id"]),
            filename="second-stop.jpg",
            captured_at="2026-07-02T18:00:00+00:00",
            latitude=37.0100,
            longitude=-122.0100,
            sha256="5" * 64,
        )

    with Session(migrated_database) as session:
        db_trip = session.get(orm.Trip, trip["id"])
        assert db_trip is not None
        initial = reconstruct_trip(db=session, trip=db_trip, geocoder=ManualGeocoder())
        assert initial.stops == 2

        first_stop_id = session.execute(
            text(
                """
                SELECT id
                FROM stops
                WHERE trip_id = :trip_id
                ORDER BY starts_at_utc
                LIMIT 1
                """
            ),
            {"trip_id": trip["id"]},
        ).scalar_one()
        session.execute(
            text(
                """
                UPDATE stops
                SET title = 'User named stop',
                    user_locked = true,
                    source = 'user_correction'
                WHERE id = :stop_id
                """
            ),
            {"stop_id": first_stop_id},
        )
        session.commit()

    with migrated_database.begin() as connection:
        insert_media(
            connection,
            trip_id=cast(UUID, trip["id"]),
            member_id=cast(UUID, owner_member["id"]),
            filename="near-existing-stop.jpg",
            captured_at="2026-07-02T16:12:00+00:00",
            latitude=37.0001,
            longitude=-122.0001,
            sha256="6" * 64,
        )
        insert_media(
            connection,
            trip_id=cast(UUID, trip["id"]),
            member_id=cast(UUID, owner_member["id"]),
            filename="new-third-stop.jpg",
            captured_at="2026-07-02T20:00:00+00:00",
            latitude=37.0300,
            longitude=-122.0300,
            sha256="7" * 64,
        )

    with Session(migrated_database) as session:
        db_trip = session.get(orm.Trip, trip["id"])
        assert db_trip is not None
        updated = reconstruct_trip(db=session, trip=db_trip, geocoder=ManualGeocoder())

        assert updated.stops == 3
        assert (
            session.execute(
                text("SELECT title FROM stops WHERE id = :stop_id"),
                {"stop_id": first_stop_id},
            ).scalar_one()
            == "User named stop"
        )
        assert (
            session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM moment_media mm
                    JOIN moments mo ON mo.id = mm.moment_id
                    WHERE mo.stop_id = :stop_id
                    """
                ),
                {"stop_id": first_stop_id},
            ).scalar_one()
            == 2
        )
        assert (
            session.execute(
                text("SELECT COUNT(*) FROM trip_legs WHERE trip_id = :trip_id"),
                {"trip_id": trip["id"]},
            ).scalar_one()
            >= 2
        )
        latest_summary = session.execute(
            text(
                """
                SELECT summary
                FROM reconstruction_runs
                WHERE trip_id = :trip_id
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
            ),
            {"trip_id": trip["id"]},
        ).scalar_one()
        assert latest_summary["mode"] == "incremental"
        assert latest_summary["assignedMedia"] == 2
