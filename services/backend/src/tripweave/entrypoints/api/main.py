from datetime import UTC, datetime
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.engine import Engine

from tripweave.adapters.database import check_database, create_database_engine, get_postgis_version
from tripweave.adapters.worker_heartbeat import read_heartbeat
from tripweave.config import Settings, get_settings
from tripweave.logging import configure_logging


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    resolved_engine = engine or create_database_engine(resolved_settings)

    app = FastAPI(title="TripWeave API", version="0.1.0")
    app.state.settings = resolved_settings
    app.state.engine = resolved_engine

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready() -> JSONResponse:
        checks = readiness_checks(app.state.engine)
        status_code = 200 if checks["ready"] else 503
        return JSONResponse(checks, status_code=status_code)

    @app.get("/status")
    def status() -> JSONResponse:
        payload = readiness_checks(app.state.engine)
        payload["worker"] = worker_status(app.state.settings)
        return JSONResponse(payload, status_code=200 if payload["ready"] else 503)

    return app


def readiness_checks(engine: Engine) -> dict[str, Any]:
    database: dict[str, Any] = {"ok": False}
    postgis: dict[str, Any] = {"ok": False}
    try:
        check_database(engine)
        database["ok"] = True
    except Exception as exc:
        database["error"] = str(exc)

    if database["ok"]:
        try:
            postgis["version"] = get_postgis_version(engine)
            postgis["ok"] = True
        except Exception as exc:
            postgis["error"] = str(exc)

    return {
        "ready": bool(database["ok"] and postgis["ok"]),
        "api": {"ok": True},
        "database": database,
        "postgis": postgis,
    }


def worker_status(settings: Settings) -> dict[str, Any]:
    heartbeat = read_heartbeat(settings.blob_dir)
    if heartbeat is None:
        return {"ok": False, "error": "worker heartbeat not found"}

    try:
        updated_at = datetime.fromisoformat(heartbeat["updated_at"])
    except ValueError:
        return {"ok": False, "error": "worker heartbeat timestamp is invalid"}

    age_seconds = (datetime.now(UTC) - updated_at).total_seconds()
    is_fresh = age_seconds <= settings.worker_stale_seconds
    return {
        "ok": heartbeat["status"] == "ok" and is_fresh,
        "status": heartbeat["status"],
        "updated_at": heartbeat["updated_at"],
        "age_seconds": round(age_seconds, 3),
    }


app = create_app()


def run() -> None:
    uvicorn.run("tripweave.entrypoints.api.main:app", host="0.0.0.0", port=8000)
