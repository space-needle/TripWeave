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
from tripweave.ports.geocoder import GeocodeResult


class CountingGeocoder:
    def __init__(self) -> None:
        self.calls: list[tuple[float, float]] = []

    def reverse_geocode(
        self, *, latitude: float, longitude: float, language_code: str | None = None
    ) -> GeocodeResult:
        self.calls.append((latitude, longitude))
        return GeocodeResult(name=f"Place {len(self.calls)}", confidence=0.88, source="test")

    def name_for_point(
        self, *, latitude: float, longitude: float, language_code: str | None = None
    ) -> GeocodeResult:
        return self.reverse_geocode(
            latitude=latitude, longitude=longitude, language_code=language_code
        )


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


def test_korea_country_boundary_selects_korean_and_defaults_to_english(
    migrated_database: Engine,
) -> None:
    query = text(
        """
        SELECT country_code
        FROM country_boundaries
        WHERE ST_Covers(
            boundary,
            ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography
        )
        LIMIT 1
        """
    )
    with migrated_database.connect() as connection:
        seoul_country = connection.execute(
            query, {"latitude": 37.5665, "longitude": 126.9780}
        ).scalar_one_or_none()
        tokyo_country = connection.execute(
            query, {"latitude": 35.6762, "longitude": 139.6503}
        ).scalar_one_or_none()

    assert seoul_country == "KR"
    assert tokyo_country is None


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
        geocoder = CountingGeocoder()
        summary = reconstruct_trip(db=session, trip=db_trip, geocoder=geocoder)
        assert summary.days == 2
        assert summary.stops >= 4
        assert summary.moments >= 4
        assert summary.review_items == 2
        assert len(geocoder.calls) == summary.stops

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

        locked_stop = (
            session.execute(
                text("SELECT id, trip_day_id, place_id FROM stops ORDER BY starts_at_utc LIMIT 1")
            )
            .mappings()
            .one()
        )
        session.execute(
            text("UPDATE stops SET user_locked = true WHERE id = :id"),
            {"id": locked_stop["id"]},
        )
        session.execute(
            text("UPDATE trip_days SET user_locked = true WHERE id = :id"),
            {"id": locked_stop["trip_day_id"]},
        )
        session.execute(
            text(
                """
                WITH duplicate_run AS (
                    INSERT INTO reconstruction_runs (
                        trip_id,
                        state,
                        source,
                        confidence,
                        algorithm_version,
                        algorithm_config,
                        user_locked,
                        finished_at
                    )
                    VALUES (
                        :trip_id,
                        'failed',
                        'automation',
                        1.0,
                        'test_duplicate',
                        '{}'::jsonb,
                        false,
                        now()
                    )
                    RETURNING id
                )
                INSERT INTO trip_days (
                    trip_id,
                    day_date,
                    title,
                    position,
                    starts_at_utc,
                    ends_at_utc,
                    source,
                    confidence,
                    algorithm_version,
                    reconstruction_run_id,
                    user_locked
                )
                SELECT
                    day.trip_id,
                    day.day_date,
                    'Duplicate day',
                    day.position,
                    day.starts_at_utc,
                    day.ends_at_utc,
                    'user_correction',
                    1.0,
                    'test_duplicate',
                    duplicate_run.id,
                    true
                FROM trip_days day, duplicate_run
                WHERE day.id = :day_id
                """
            ),
            {"trip_id": trip["id"], "day_id": locked_stop["trip_day_id"]},
        )
        session.commit()

        second = reconstruct_trip(db=session, trip=db_trip, geocoder=ManualGeocoder())
        assert second.days == summary.days
        assert second.review_items == summary.review_items
        preserved_stop = session.execute(
            text("SELECT COUNT(*) FROM stops WHERE id = :id AND user_locked = true"),
            {"id": locked_stop["id"]},
        ).scalar_one()
        preserved_place = session.execute(
            text("SELECT COUNT(*) FROM places WHERE id = :id"),
            {"id": locked_stop["place_id"]},
        ).scalar_one()
        assert preserved_stop == 1
        assert preserved_place == 1
        latest_run_id = session.execute(
            text(
                """
                SELECT id
                FROM reconstruction_runs
                WHERE trip_id = :trip_id
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
            ),
            {"trip_id": trip["id"]},
        ).scalar_one()
        duplicate_visible_dates = session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT day_date
                    FROM trip_days
                    WHERE trip_id = :trip_id
                        AND (reconstruction_run_id = :run_id OR user_locked = true)
                    GROUP BY day_date
                    HAVING COUNT(*) > 1
                ) duplicate_dates
                """
            ),
            {"trip_id": trip["id"], "run_id": latest_run_id},
        ).scalar_one()
        assert duplicate_visible_dates == 0


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
        insert_media(
            connection,
            trip_id=cast(UUID, trip["id"]),
            member_id=cast(UUID, owner_member["id"]),
            filename="new-third-stop-same-moment.jpg",
            captured_at="2026-07-02T20:02:00+00:00",
            latitude=37.0301,
            longitude=-122.0301,
            sha256="8" * 64,
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
        assert latest_summary["assignedMedia"] == 3
        assert (
            session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM moment_participants mp
                    JOIN moments mo ON mo.id = mp.moment_id
                    JOIN moment_media mm ON mm.moment_id = mo.id
                    JOIN media_items mi ON mi.id = mm.media_item_id
                    WHERE mi.original_filename IN (
                        'new-third-stop.jpg',
                        'new-third-stop-same-moment.jpg'
                    )
                    """
                )
            ).scalar_one()
            == 1
        )


def test_reconstruction_reuses_owner_stop_rename_on_future_trip(
    migrated_database: Engine,
) -> None:
    owner = factories.user_row(email="owner-remembered-stop@example.com")
    other_user = factories.user_row(email="other-remembered-stop@example.com")
    previous_trip = factories.trip_row(created_by=cast(UUID, owner["id"]))
    other_trip = factories.trip_row(created_by=cast(UUID, other_user["id"]))
    future_trip = factories.trip_row(created_by=cast(UUID, owner["id"]))
    previous_member = factories.member_row(
        trip_id=cast(UUID, previous_trip["id"]), user_id=cast(UUID, owner["id"])
    )
    previous_member["role"] = "owner"
    other_member = factories.member_row(
        trip_id=cast(UUID, other_trip["id"]), user_id=cast(UUID, other_user["id"])
    )
    other_member["role"] = "owner"
    future_member = factories.member_row(
        trip_id=cast(UUID, future_trip["id"]), user_id=cast(UUID, owner["id"])
    )
    future_member["role"] = "owner"

    with migrated_database.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO users (id, email, password_hash, display_name)
                VALUES (:id, :email, :password_hash, :display_name)
                """
            ),
            [owner, other_user],
        )
        connection.execute(
            text(
                """
                INSERT INTO trips (id, title, timezone_id, created_by)
                VALUES (:id, :title, :timezone_id, :created_by)
                """
            ),
            [previous_trip, other_trip, future_trip],
        )
        connection.execute(
            text(
                """
                INSERT INTO trip_members (id, trip_id, user_id, role, display_name)
                VALUES (:id, :trip_id, :user_id, :role, :display_name)
                """
            ),
            [previous_member, other_member, future_member],
        )
        insert_media(
            connection,
            trip_id=cast(UUID, previous_trip["id"]),
            member_id=cast(UUID, previous_member["id"]),
            filename="remembered-owner-previous.jpg",
            captured_at="2026-07-02T16:00:00+00:00",
            latitude=37.0000,
            longitude=-122.0000,
            sha256="a" * 64,
        )
        insert_media(
            connection,
            trip_id=cast(UUID, other_trip["id"]),
            member_id=cast(UUID, other_member["id"]),
            filename="remembered-other-previous.jpg",
            captured_at="2026-07-02T16:00:00+00:00",
            latitude=37.0000,
            longitude=-122.0000,
            sha256="b" * 64,
        )

    with Session(migrated_database) as session:
        db_previous_trip = session.get(orm.Trip, previous_trip["id"])
        db_other_trip = session.get(orm.Trip, other_trip["id"])
        assert db_previous_trip is not None
        assert db_other_trip is not None
        reconstruct_trip(db=session, trip=db_previous_trip, geocoder=CountingGeocoder())
        reconstruct_trip(db=session, trip=db_other_trip, geocoder=CountingGeocoder())

        previous_stop_id = session.execute(
            text(
                """
                SELECT id
                FROM stops
                WHERE trip_id = :trip_id
                ORDER BY starts_at_utc
                LIMIT 1
                """
            ),
            {"trip_id": previous_trip["id"]},
        ).scalar_one()
        other_stop_id = session.execute(
            text(
                """
                SELECT id
                FROM stops
                WHERE trip_id = :trip_id
                ORDER BY starts_at_utc
                LIMIT 1
                """
            ),
            {"trip_id": other_trip["id"]},
        ).scalar_one()
        session.execute(
            text(
                """
                UPDATE stops
                SET title = :title,
                    user_locked = true,
                    source = 'user_correction'
                WHERE id = :stop_id
                """
            ),
            [
                {"stop_id": previous_stop_id, "title": "Owner remembered cafe"},
                {"stop_id": other_stop_id, "title": "Other remembered cafe"},
            ],
        )
        session.execute(
            text(
                """
                INSERT INTO edit_operations (
                    trip_id, operation_type, actor_user_id, actor_member_id,
                    target_type, target_id, payload, before_values, after_values
                )
                VALUES (
                    :trip_id, 'rename_stop', :actor_user_id, :actor_member_id,
                    'stop', :target_id, '{}'::jsonb,
                    CAST(:before_values AS jsonb),
                    CAST(:after_values AS jsonb)
                )
                """
            ),
            [
                {
                    "trip_id": previous_trip["id"],
                    "actor_user_id": owner["id"],
                    "actor_member_id": previous_member["id"],
                    "target_id": previous_stop_id,
                    "before_values": '{"title": "Place 1"}',
                    "after_values": '{"title": "Owner remembered cafe"}',
                },
                {
                    "trip_id": other_trip["id"],
                    "actor_user_id": other_user["id"],
                    "actor_member_id": other_member["id"],
                    "target_id": other_stop_id,
                    "before_values": '{"title": "Place 1"}',
                    "after_values": '{"title": "Other remembered cafe"}',
                },
            ],
        )
        session.commit()

    with migrated_database.begin() as connection:
        insert_media(
            connection,
            trip_id=cast(UUID, future_trip["id"]),
            member_id=cast(UUID, future_member["id"]),
            filename="remembered-owner-future.jpg",
            captured_at="2026-08-02T16:00:00+00:00",
            latitude=37.0001,
            longitude=-122.0001,
            sha256="c" * 64,
        )

    with Session(migrated_database) as session:
        db_future_trip = session.get(orm.Trip, future_trip["id"])
        assert db_future_trip is not None
        reconstruct_trip(db=session, trip=db_future_trip, geocoder=CountingGeocoder())
        remembered_title = session.execute(
            text("SELECT title FROM stops WHERE trip_id = :trip_id"),
            {"trip_id": future_trip["id"]},
        ).scalar_one()

    assert remembered_title == "Owner remembered cafe"


def test_full_rebuild_preserves_media_under_locked_stops(
    migrated_database: Engine,
) -> None:
    user = factories.user_row(email="owner-full-rebuild@example.com")
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
            filename="locked-stop-photo.jpg",
            captured_at="2026-07-02T16:00:00+00:00",
            latitude=37.0000,
            longitude=-122.0000,
            sha256="9" * 64,
        )
        insert_media(
            connection,
            trip_id=cast(UUID, trip["id"]),
            member_id=cast(UUID, owner_member["id"]),
            filename="locked-stop-photo-2.jpg",
            captured_at="2026-07-02T16:03:00+00:00",
            latitude=37.0001,
            longitude=-122.0001,
            sha256="b" * 64,
        )
        insert_media(
            connection,
            trip_id=cast(UUID, trip["id"]),
            member_id=cast(UUID, owner_member["id"]),
            filename="other-stop-photo.jpg",
            captured_at="2026-07-02T18:00:00+00:00",
            latitude=37.0100,
            longitude=-122.0100,
            sha256="a" * 64,
        )

    with Session(migrated_database) as session:
        db_trip = session.get(orm.Trip, trip["id"])
        assert db_trip is not None
        initial = reconstruct_trip(db=session, trip=db_trip, geocoder=ManualGeocoder())
        assert initial.stops == 2

        locked_stop_id = session.execute(
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
                SET user_locked = true,
                    source = 'user_correction'
                WHERE id = :stop_id
                """
            ),
            {"stop_id": locked_stop_id},
        )
        session.commit()

        rebuilt = reconstruct_trip(db=session, trip=db_trip, geocoder=ManualGeocoder())
        assert rebuilt.days == 1

        latest_run_id = session.execute(
            text(
                """
                SELECT id
                FROM reconstruction_runs
                WHERE trip_id = :trip_id
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
            ),
            {"trip_id": trip["id"]},
        ).scalar_one()
        locked_stop_visible_media_count = session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM moment_media mm
                JOIN moments mo ON mo.id = mm.moment_id
                WHERE mo.stop_id = :stop_id
                    AND (mm.reconstruction_run_id = :run_id OR mm.user_locked = true)
                    AND (mo.reconstruction_run_id = :run_id OR mo.user_locked = true)
                """
            ),
            {"stop_id": locked_stop_id, "run_id": latest_run_id},
        ).scalar_one()
        visible_stop_count = session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM stops
                WHERE trip_id = :trip_id
                    AND (reconstruction_run_id = :run_id OR user_locked = true)
                """
            ),
            {"trip_id": trip["id"], "run_id": latest_run_id},
        ).scalar_one()
        duplicate_locked_media_stop_count = session.execute(
            text(
                """
                SELECT COUNT(DISTINCT mo.stop_id)
                FROM moment_media mm
                JOIN moments mo ON mo.id = mm.moment_id
                JOIN media_items mi ON mi.id = mm.media_item_id
                WHERE mi.original_filename = 'locked-stop-photo.jpg'
                    AND (mm.reconstruction_run_id = :run_id OR mm.user_locked = true)
                    AND (mo.reconstruction_run_id = :run_id OR mo.user_locked = true)
                """
            ),
            {"run_id": latest_run_id},
        ).scalar_one()
        locked_stop_participant_count = session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM moment_participants mp
                JOIN moments mo ON mo.id = mp.moment_id
                WHERE mo.stop_id = :stop_id
                    AND (mp.reconstruction_run_id = :run_id OR mp.user_locked = true)
                    AND (mo.reconstruction_run_id = :run_id OR mo.user_locked = true)
                """
            ),
            {"stop_id": locked_stop_id, "run_id": latest_run_id},
        ).scalar_one()

        assert locked_stop_visible_media_count == 2
        assert visible_stop_count == 2
        assert duplicate_locked_media_stop_count == 1
        assert locked_stop_participant_count == 1


def test_full_rebuild_preserves_locked_area_visit_dependencies(
    migrated_database: Engine,
) -> None:
    user = factories.user_row(email="owner-full-rebuild-area@example.com")
    trip = factories.trip_row(
        created_by=cast(UUID, user["id"]),
        timezone_id="Asia/Seoul",
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
        for index, latitude in enumerate([35.0000, 35.0018, 35.0036], start=1):
            insert_media(
                connection,
                trip_id=cast(UUID, trip["id"]),
                member_id=cast(UUID, owner_member["id"]),
                filename=f"locked-area-{index}.jpg",
                captured_at=f"2026-06-08T09:{index * 10:02d}:00+00:00",
                latitude=latitude,
                longitude=127.0,
                sha256=f"{index}" * 64,
            )

    with Session(migrated_database) as session:
        db_trip = session.get(orm.Trip, trip["id"])
        assert db_trip is not None
        initial = reconstruct_trip(db=session, trip=db_trip, geocoder=ManualGeocoder())
        assert initial.stops == 3

        locked_membership = session.execute(
            text(
                """
                SELECT avs.id, avs.area_visit_id, avs.stop_id, av.trip_day_id
                FROM area_visit_stops avs
                JOIN area_visits av ON av.id = avs.area_visit_id
                WHERE avs.trip_id = :trip_id
                ORDER BY avs.sort_order
                LIMIT 1
                """
            ),
            {"trip_id": trip["id"]},
        ).one()
        session.execute(
            text(
                """
                UPDATE area_visit_stops
                SET user_locked = true,
                    membership_source = 'user_correction'
                WHERE id = :membership_id
                """
            ),
            {"membership_id": locked_membership.id},
        )
        session.commit()

        rebuilt = reconstruct_trip(db=session, trip=db_trip, geocoder=ManualGeocoder())
        assert rebuilt.days == 1

        locked_dependency_state = session.execute(
            text(
                """
                SELECT
                    avs.user_locked AS membership_locked,
                    av.user_locked AS area_locked,
                    s.user_locked AS stop_locked,
                    td.user_locked AS day_locked
                FROM area_visit_stops avs
                JOIN area_visits av ON av.id = avs.area_visit_id
                JOIN stops s ON s.id = avs.stop_id
                JOIN trip_days td ON td.id = av.trip_day_id
                WHERE avs.id = :membership_id
                """
            ),
            {"membership_id": locked_membership.id},
        ).one()
        assert locked_dependency_state.membership_locked is True
        assert locked_dependency_state.area_locked is True
        assert locked_dependency_state.stop_locked is True
        assert locked_dependency_state.day_locked is True
