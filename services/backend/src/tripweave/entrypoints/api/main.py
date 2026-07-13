# ruff: noqa: B008
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from tripweave.adapters import orm
from tripweave.adapters.database import check_database, create_database_engine, get_postgis_version
from tripweave.adapters.transactions import create_session_factory
from tripweave.adapters.worker_heartbeat import read_heartbeat
from tripweave.application.auth import (
    PasswordService,
    constant_time_equal,
    hash_token,
    new_session_secrets,
    normalize_email,
)
from tripweave.application.rate_limit import FixedWindowRateLimiter
from tripweave.config import Settings, get_settings
from tripweave.domain.enums import TripMemberRole, TripStatus, TripVisibility
from tripweave.entrypoints.api.schemas import (
    AuthResponse,
    LoginRequest,
    MeResponse,
    RegisterRequest,
    TripCreateRequest,
    TripResponse,
    TripsListResponse,
    TripUpdateRequest,
    UserResponse,
)
from tripweave.logging import configure_logging


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    user: orm.User
    session: orm.Session


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    resolved_engine = engine or create_database_engine(resolved_settings)
    session_factory = create_session_factory(resolved_engine)

    app = FastAPI(title="TripWeave API", version="0.1.0")
    app.state.settings = resolved_settings
    app.state.engine = resolved_engine
    app.state.session_factory = session_factory
    app.state.passwords = PasswordService()
    app.state.auth_rate_limiter = FixedWindowRateLimiter(
        max_attempts=resolved_settings.auth_rate_limit_max_attempts,
        window_seconds=resolved_settings.auth_rate_limit_window_seconds,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["content-type", "x-csrf-token"],
    )

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready() -> JSONResponse:
        checks = readiness_checks(app.state.engine)
        status_code = 200 if checks["ready"] else 503
        return JSONResponse(checks, status_code=status_code)

    @app.get("/status")
    def service_status() -> JSONResponse:
        payload = readiness_checks(app.state.engine)
        payload["worker"] = worker_status(app.state.settings)
        return JSONResponse(payload, status_code=200 if payload["ready"] else 503)

    def db_session() -> Iterator[DbSession]:
        db = app.state.session_factory()
        try:
            yield db
        finally:
            db.close()

    def current_user(
        request: Request,
        db: DbSession = Depends(db_session),
    ) -> AuthenticatedUser:
        token = request.cookies.get(resolved_settings.session_cookie_name)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )
        session_token_hash = hash_token(token)
        now = datetime.now(UTC)
        result = db.execute(
            select(orm.Session, orm.User)
            .join(orm.User, orm.User.id == orm.Session.user_id)
            .where(
                orm.Session.token_hash == session_token_hash,
                orm.Session.revoked_at.is_(None),
                orm.Session.expires_at > now,
            )
        ).one_or_none()
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )
        user_session, user = result
        return AuthenticatedUser(user=user, session=user_session)

    def require_csrf(request: Request) -> None:
        csrf_cookie = request.cookies.get(resolved_settings.csrf_cookie_name)
        x_csrf_token = request.headers.get("x-csrf-token")
        if (
            not csrf_cookie
            or not x_csrf_token
            or not constant_time_equal(csrf_cookie, x_csrf_token)
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF check failed")

    def set_auth_cookies(response: Response, session_token: str, csrf_token: str) -> None:
        response.set_cookie(
            resolved_settings.session_cookie_name,
            session_token,
            httponly=True,
            max_age=resolved_settings.session_lifetime_seconds,
            secure=resolved_settings.secure_cookies,
            samesite="lax",
            path="/",
        )
        response.set_cookie(
            resolved_settings.csrf_cookie_name,
            csrf_token,
            httponly=False,
            max_age=resolved_settings.session_lifetime_seconds,
            secure=resolved_settings.secure_cookies,
            samesite="lax",
            path="/",
        )

    def clear_auth_cookies(response: Response) -> None:
        response.delete_cookie(
            resolved_settings.session_cookie_name,
            path="/",
            secure=resolved_settings.secure_cookies,
            samesite="lax",
        )
        response.delete_cookie(
            resolved_settings.csrf_cookie_name,
            path="/",
            secure=resolved_settings.secure_cookies,
            samesite="lax",
        )

    def rate_limit_auth(request: Request, action: str, email: str) -> None:
        client_host = request.client.host if request.client else "unknown"
        key = f"{action}:{client_host}:{normalize_email(email)}"
        if not app.state.auth_rate_limiter.allow(key):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Try again later"
            )

    def user_response(user: orm.User) -> UserResponse:
        return UserResponse(id=user.id, email=user.email, display_name=user.display_name)

    def auth_response(user: orm.User, csrf_token: str) -> AuthResponse:
        return AuthResponse(user=user_response(user), csrfToken=csrf_token)

    def create_session_for_user(db: DbSession, user: orm.User) -> tuple[orm.Session, str, str]:
        secrets = new_session_secrets(resolved_settings.session_lifetime_seconds)
        user_session = orm.Session(
            user_id=user.id,
            token_hash=secrets.session_token_hash,
            expires_at=secrets.expires_at,
        )
        db.add(user_session)
        db.flush()
        return user_session, secrets.session_token, secrets.csrf_token

    @app.post("/auth/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
    def register(
        payload: RegisterRequest,
        request: Request,
        response: Response,
        db: DbSession = Depends(db_session),
    ) -> AuthResponse:
        rate_limit_auth(request, "register", payload.email)
        normalized_email = normalize_email(payload.email)
        password_hash = app.state.passwords.hash_password(payload.password)
        try:
            user = orm.User(
                email=normalized_email,
                password_hash=password_hash,
                display_name=payload.display_name.strip(),
            )
            db.add(user)
            db.flush()
            _, session_token, csrf_token = create_session_for_user(db, user)
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unable to register with those credentials",
            ) from exc
        set_auth_cookies(response, session_token, csrf_token)
        return auth_response(user, csrf_token)

    @app.post("/auth/login", response_model=AuthResponse)
    def login(
        payload: LoginRequest,
        request: Request,
        response: Response,
        db: DbSession = Depends(db_session),
    ) -> AuthResponse:
        rate_limit_auth(request, "login", payload.email)
        user = db.execute(
            select(orm.User).where(orm.User.email == normalize_email(payload.email))
        ).scalar_one_or_none()
        if user is None or not app.state.passwords.verify_password(
            user.password_hash, payload.password
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
            )
        _, session_token, csrf_token = create_session_for_user(db, user)
        db.commit()
        set_auth_cookies(response, session_token, csrf_token)
        return auth_response(user, csrf_token)

    @app.post("/auth/logout")
    def logout(
        request: Request,
        response: Response,
        auth: AuthenticatedUser = Depends(current_user),
        db: DbSession = Depends(db_session),
    ) -> dict[str, str]:
        require_csrf(request)
        session_record = db.get(orm.Session, auth.session.id)
        if session_record is not None:
            session_record.revoked_at = datetime.now(UTC)
        db.commit()
        clear_auth_cookies(response)
        return {"status": "ok"}

    @app.get("/auth/me", response_model=MeResponse)
    def me(auth: AuthenticatedUser = Depends(current_user)) -> MeResponse:
        return MeResponse(user=user_response(auth.user))

    def member_for_trip(db: DbSession, trip_id: UUID, user_id: UUID) -> orm.TripMember | None:
        return db.execute(
            select(orm.TripMember).where(
                orm.TripMember.trip_id == trip_id,
                orm.TripMember.user_id == user_id,
                orm.TripMember.removed_at.is_(None),
            )
        ).scalar_one_or_none()

    def trip_response(trip: orm.Trip, role: str) -> TripResponse:
        return TripResponse(
            id=trip.id,
            title=trip.title,
            description=trip.description,
            startDate=trip.start_date,
            endDate=trip.end_date,
            timezoneId=trip.timezone_id,
            dayCutoffHour=trip.day_cutoff_hour,
            status=trip.status,
            visibility=trip.visibility,
            role=role,
            createdAt=trip.created_at,
            updatedAt=trip.updated_at,
        )

    @app.post("/trips", response_model=TripResponse, status_code=status.HTTP_201_CREATED)
    def create_trip(
        payload: TripCreateRequest,
        request: Request,
        auth: AuthenticatedUser = Depends(current_user),
        db: DbSession = Depends(db_session),
    ) -> TripResponse:
        require_csrf(request)
        now = datetime.now(UTC)
        trip = orm.Trip(
            title=payload.title.strip(),
            description=payload.description,
            start_date=payload.start_date,
            end_date=payload.end_date,
            timezone_id=payload.timezone_id,
            day_cutoff_hour=payload.day_cutoff_hour,
            status=TripStatus.ACTIVE.value,
            visibility=TripVisibility.PRIVATE.value,
            created_by=auth.user.id,
            updated_at=now,
        )
        db.add(trip)
        db.flush()
        member = orm.TripMember(
            trip_id=trip.id,
            user_id=auth.user.id,
            role=TripMemberRole.OWNER.value,
            display_name=auth.user.display_name,
        )
        db.add(member)
        db.flush()
        db.commit()
        return trip_response(trip, member.role)

    @app.get("/trips", response_model=TripsListResponse)
    def list_trips(
        auth: AuthenticatedUser = Depends(current_user),
        db: DbSession = Depends(db_session),
    ) -> TripsListResponse:
        rows = db.execute(
            select(orm.Trip, orm.TripMember.role)
            .join(orm.TripMember, orm.TripMember.trip_id == orm.Trip.id)
            .where(
                orm.TripMember.user_id == auth.user.id,
                orm.TripMember.removed_at.is_(None),
            )
            .order_by(orm.Trip.created_at.desc(), orm.Trip.id)
        ).all()
        return TripsListResponse(trips=[trip_response(trip, role) for trip, role in rows])

    @app.get("/trips/{trip_id}", response_model=TripResponse)
    def get_trip(
        trip_id: UUID,
        auth: AuthenticatedUser = Depends(current_user),
        db: DbSession = Depends(db_session),
    ) -> TripResponse:
        member = member_for_trip(db, trip_id, auth.user.id)
        if member is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
        trip = db.get(orm.Trip, trip_id)
        if trip is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
        return trip_response(trip, member.role)

    @app.patch("/trips/{trip_id}", response_model=TripResponse)
    def update_trip(
        trip_id: UUID,
        payload: TripUpdateRequest,
        request: Request,
        auth: AuthenticatedUser = Depends(current_user),
        db: DbSession = Depends(db_session),
    ) -> TripResponse:
        require_csrf(request)
        member = member_for_trip(db, trip_id, auth.user.id)
        if member is None or member.role not in {
            TripMemberRole.OWNER.value,
            TripMemberRole.EDITOR.value,
        }:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
        trip = db.get(orm.Trip, trip_id)
        if trip is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
        updates = payload.model_dump(exclude_unset=True, by_alias=False)
        for field_name, value in updates.items():
            setattr(trip, field_name, value)
        trip.updated_at = datetime.now(UTC)
        db.commit()
        return trip_response(trip, member.role)

    @app.delete("/trips/{trip_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_trip(
        trip_id: UUID,
        request: Request,
        auth: AuthenticatedUser = Depends(current_user),
        db: DbSession = Depends(db_session),
    ) -> Response:
        require_csrf(request)
        member = member_for_trip(db, trip_id, auth.user.id)
        if member is None or member.role != TripMemberRole.OWNER.value:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
        trip = db.get(orm.Trip, trip_id)
        if trip is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
        db.delete(trip)
        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

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
