from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import PostgresDsn

from tripweave.config import Settings
from tripweave.entrypoints.api.main import create_app


class FakeEngine:
    should_fail_database = False
    should_fail_postgis = False


def test_liveness_returns_ok() -> None:
    settings = Settings(
        DATABASE_URL=PostgresDsn("postgresql+psycopg://user:pass@localhost:5432/tripweave"),
        TRIPWEAVE_BLOB_DIR=Path("/tmp/tripweave-test"),
    )
    client = TestClient(create_app(settings=settings, engine=FakeEngine()))  # type: ignore[arg-type]

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
