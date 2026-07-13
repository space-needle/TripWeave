import os
from collections.abc import Iterator
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from alembic import command
from tests import factories


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

    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    try:
        yield engine
    finally:
        command.downgrade(config, "base")


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
