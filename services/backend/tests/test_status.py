from datetime import UTC, datetime
from pathlib import Path

from pydantic import PostgresDsn

from tripweave.adapters.worker_heartbeat import write_heartbeat
from tripweave.config import Settings
from tripweave.entrypoints.api.main import worker_status


def settings_for(blob_dir: Path) -> Settings:
    return Settings(
        DATABASE_URL=PostgresDsn("postgresql+psycopg://user:pass@localhost:5432/tripweave"),
        TRIPWEAVE_BLOB_DIR=blob_dir,
        TRIPWEAVE_WORKER_STALE_SECONDS=90,
    )


def test_worker_status_is_healthy_for_recent_heartbeat(tmp_path: Path) -> None:
    write_heartbeat(tmp_path)

    result = worker_status(settings_for(tmp_path))

    assert result["ok"] is True
    assert result["status"] == "ok"


def test_worker_status_reports_missing_heartbeat(tmp_path: Path) -> None:
    result = worker_status(settings_for(tmp_path))

    assert result["ok"] is False
    assert "not found" in result["error"]


def test_worker_status_reports_stale_heartbeat(tmp_path: Path) -> None:
    heartbeat = tmp_path / "worker-heartbeat.json"
    heartbeat.write_text(
        '{"status": "ok", "updated_at": "2020-01-01T00:00:00+00:00"}\n',
        encoding="utf-8",
    )

    result = worker_status(settings_for(tmp_path))

    assert result["ok"] is False
    assert result["age_seconds"] > 90
    assert datetime.fromisoformat(result["updated_at"]).tzinfo == UTC
