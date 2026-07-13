# ruff: noqa: B008
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from tripweave.adapters import orm
from tripweave.adapters.database import check_database, create_database_engine, get_postgis_version
from tripweave.adapters.local_blob_store import (
    BlobNotFoundError,
    BlobSizeExceededError,
    InvalidGrantError,
    LocalBlobStore,
)
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
from tripweave.domain.enums import (
    MediaType,
    ProcessingJobType,
    ProcessingTargetType,
    TripMemberRole,
    TripStatus,
    TripVisibility,
    UploadState,
)
from tripweave.domain.storage import BlobRef, UploadGrant, UploadGrantRequest
from tripweave.entrypoints.api.schemas import (
    AuthResponse,
    BlobRefResponse,
    CompleteUploadFileResponse,
    LoginRequest,
    MeResponse,
    RegisterRequest,
    TripCreateRequest,
    TripResponse,
    TripsListResponse,
    TripUpdateRequest,
    UploadFileResponse,
    UploadGrantResponse,
    UploadSessionCreateRequest,
    UploadSessionResponse,
    UploadSessionsListResponse,
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
    app.state.blob_store = LocalBlobStore(
        root=resolved_settings.blob_dir,
        store_aliases=resolved_settings.store_aliases,
        signing_secret=resolved_settings.storage_signing_secret,
        public_base_url=resolved_settings.public_api_base_url,
        grant_lifetime_seconds=resolved_settings.upload_grant_lifetime_seconds,
        maximum_single_upload_bytes=resolved_settings.upload_max_file_bytes,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
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

    def upload_limits() -> dict[str, object]:
        return {
            "maxFilesPerTrip": resolved_settings.upload_max_files_per_trip,
            "maxFileBytes": resolved_settings.upload_max_file_bytes,
            "maxTripBytes": resolved_settings.upload_max_trip_bytes,
            "allowedExtensions": sorted(resolved_settings.allowed_upload_extensions),
            "allowedMimeTypes": sorted(resolved_settings.allowed_upload_mime_types),
        }

    def validate_upload_file(filename: str, byte_size: int, mime_type: str) -> None:
        extension = PurePosixPath(filename).suffix.lower()
        if byte_size <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty")
        if byte_size > resolved_settings.upload_max_file_bytes:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is too large")
        if extension not in resolved_settings.allowed_upload_extensions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="File extension is not allowed"
            )
        if mime_type.strip().lower() not in resolved_settings.allowed_upload_mime_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="MIME type is not allowed"
            )

    def storage_filename(filename: str) -> str:
        cleaned = PurePosixPath(filename.replace("\\", "/")).name
        if not cleaned or cleaned in {".", ".."}:
            return "upload"
        return cleaned

    def upload_grant_response(grant: UploadGrant) -> UploadGrantResponse:
        return UploadGrantResponse(
            blobRef=BlobRefResponse(
                storeAlias=grant.blob_ref.store_alias,
                objectKey=grant.blob_ref.object_key,
                checksumAlgorithm=grant.blob_ref.checksum_algorithm,
                checksum=grant.blob_ref.checksum,
                sizeBytes=grant.blob_ref.size_bytes,
                contentType=grant.blob_ref.content_type,
            ),
            method=grant.method.value,
            url=grant.url,
            headers=grant.headers,
            expiresAt=grant.expires_at,
            maxSizeBytes=grant.max_size_bytes,
            contentType=grant.content_type,
        )

    def upload_file_response(
        upload_file: orm.UploadFile,
        *,
        include_grant: bool,
    ) -> UploadFileResponse:
        grant: UploadGrantResponse | None = None
        if include_grant and upload_file.state in {
            UploadState.REGISTERED.value,
            UploadState.TRANSFERRING.value,
        }:
            blob_ref = BlobRef(
                store_alias=upload_file.store_alias,
                object_key=upload_file.object_key,
            )
            grant = upload_grant_response(
                app.state.blob_store.create_upload_grant(
                    UploadGrantRequest(
                        blob_ref=blob_ref,
                        max_size_bytes=upload_file.declared_byte_size
                        or resolved_settings.upload_max_file_bytes,
                        content_type=upload_file.declared_mime_type,
                    )
                )
            )
        return UploadFileResponse(
            id=upload_file.id,
            state=upload_file.state,
            filename=upload_file.original_filename,
            byteSize=upload_file.declared_byte_size,
            mimeType=upload_file.declared_mime_type,
            storeAlias=upload_file.store_alias,
            objectKey=upload_file.object_key,
            sha256=upload_file.sha256,
            mediaItemId=upload_file.media_item_id,
            errorMessage=upload_file.error_message,
            grant=grant,
        )

    def upload_session_response(
        db: DbSession,
        upload_session: orm.UploadSession,
        *,
        include_grants: bool,
    ) -> UploadSessionResponse:
        files = db.scalars(
            select(orm.UploadFile)
            .where(orm.UploadFile.upload_session_id == upload_session.id)
            .order_by(orm.UploadFile.created_at, orm.UploadFile.id)
        ).all()
        return UploadSessionResponse(
            id=upload_session.id,
            tripId=upload_session.trip_id,
            state=upload_session.state,
            declaredFileCount=upload_session.declared_file_count,
            declaredTotalBytes=upload_session.declared_total_bytes,
            files=[
                upload_file_response(upload_file, include_grant=include_grants)
                for upload_file in files
            ],
            limits=upload_limits(),
        )

    def upload_session_response_from_files(
        upload_session: orm.UploadSession,
        files: list[orm.UploadFile],
        *,
        include_grants: bool,
    ) -> UploadSessionResponse:
        return UploadSessionResponse(
            id=upload_session.id,
            tripId=upload_session.trip_id,
            state=upload_session.state,
            declaredFileCount=upload_session.declared_file_count,
            declaredTotalBytes=upload_session.declared_total_bytes,
            files=[
                upload_file_response(upload_file, include_grant=include_grants)
                for upload_file in files
            ],
            limits=upload_limits(),
        )

    def upload_session_for_user(
        db: DbSession,
        upload_session_id: UUID,
        user_id: UUID,
    ) -> tuple[orm.UploadSession, orm.TripMember]:
        upload_session = db.get(orm.UploadSession, upload_session_id)
        if upload_session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Upload session not found"
            )
        member = member_for_trip(db, upload_session.trip_id, user_id)
        if member is None or member.id != upload_session.member_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Upload session not found"
            )
        return upload_session, member

    @app.post(
        "/trips/{trip_id}/upload-sessions",
        response_model=UploadSessionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_upload_session(
        trip_id: UUID,
        payload: UploadSessionCreateRequest,
        request: Request,
        auth: AuthenticatedUser = Depends(current_user),
        db: DbSession = Depends(db_session),
    ) -> UploadSessionResponse:
        require_csrf(request)
        member = member_for_trip(db, trip_id, auth.user.id)
        if member is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")

        if len(payload.files) > resolved_settings.upload_max_files_per_trip:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Too many files for one trip"
            )
        total_bytes = sum(file.byte_size for file in payload.files)
        if total_bytes > resolved_settings.upload_max_trip_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Trip upload is too large"
            )
        for file in payload.files:
            validate_upload_file(file.filename, file.byte_size, file.mime_type)

        existing_count = db.execute(
            select(func.count())
            .select_from(orm.MediaItem)
            .where(orm.MediaItem.trip_id == trip_id, orm.MediaItem.deleted_at.is_(None))
        ).scalar_one()
        existing_bytes = db.execute(
            select(func.coalesce(func.sum(orm.MediaItem.byte_size), 0)).where(
                orm.MediaItem.trip_id == trip_id,
                orm.MediaItem.deleted_at.is_(None),
            )
        ).scalar_one()
        if existing_count + len(payload.files) > resolved_settings.upload_max_files_per_trip:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Trip file limit exceeded"
            )
        current_trip_bytes = int(existing_bytes or 0)
        if current_trip_bytes + total_bytes > resolved_settings.upload_max_trip_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Trip byte limit exceeded"
            )

        now = datetime.now(UTC)
        upload_session = orm.UploadSession(
            trip_id=trip_id,
            member_id=member.id,
            state=UploadState.REGISTERED.value,
            declared_file_count=len(payload.files),
            declared_total_bytes=total_bytes,
            registered_at=now,
            updated_at=now,
        )
        db.add(upload_session)
        db.flush()
        created_files: list[orm.UploadFile] = []
        for file in payload.files:
            upload_file = orm.UploadFile(
                upload_session_id=upload_session.id,
                state=UploadState.REGISTERED.value,
                original_filename=file.filename,
                declared_byte_size=file.byte_size,
                declared_mime_type=file.mime_type.strip().lower(),
                store_alias="media_private",
                object_key=(
                    f"trips/{trip_id}/upload-sessions/{upload_session.id}/files/{file.filename}"
                ),
            )
            db.add(upload_file)
            db.flush()
            upload_file.object_key = (
                f"trips/{trip_id}/upload-sessions/{upload_session.id}/"
                f"files/{upload_file.id}/{storage_filename(file.filename)}"
            )
            created_files.append(upload_file)
        db.commit()
        return upload_session_response_from_files(
            upload_session, created_files, include_grants=True
        )

    @app.get("/upload-sessions", response_model=UploadSessionsListResponse)
    def list_upload_sessions(
        trip_id: UUID,
        auth: AuthenticatedUser = Depends(current_user),
        db: DbSession = Depends(db_session),
    ) -> UploadSessionsListResponse:
        member = member_for_trip(db, trip_id, auth.user.id)
        if member is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
        sessions = db.scalars(
            select(orm.UploadSession)
            .where(orm.UploadSession.trip_id == trip_id, orm.UploadSession.member_id == member.id)
            .order_by(orm.UploadSession.created_at.desc(), orm.UploadSession.id)
        ).all()
        return UploadSessionsListResponse(
            uploadSessions=[
                upload_session_response(db, upload_session, include_grants=True)
                for upload_session in sessions
            ]
        )

    @app.get("/upload-sessions/{upload_session_id}", response_model=UploadSessionResponse)
    def get_upload_session(
        upload_session_id: UUID,
        auth: AuthenticatedUser = Depends(current_user),
        db: DbSession = Depends(db_session),
    ) -> UploadSessionResponse:
        upload_session, _ = upload_session_for_user(db, upload_session_id, auth.user.id)
        return upload_session_response(db, upload_session, include_grants=True)

    @app.put("/blob-upload/{token}")
    async def upload_blob(token: str, request: Request) -> dict[str, object]:
        try:
            blob_ref, max_size_bytes, content_type = app.state.blob_store.verify_upload_token(token)
            metadata = await app.state.blob_store.put_chunks(
                blob_ref,
                request.stream(),
                max_size_bytes=max_size_bytes,
                content_type=content_type,
            )
        except InvalidGrantError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except BlobSizeExceededError as exc:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return {
            "sizeBytes": metadata.size_bytes,
            "checksumAlgorithm": metadata.checksum_algorithm,
            "checksum": metadata.checksum,
        }

    @app.post(
        "/upload-files/{upload_file_id}/complete",
        response_model=CompleteUploadFileResponse,
    )
    def complete_upload_file(
        upload_file_id: UUID,
        request: Request,
        auth: AuthenticatedUser = Depends(current_user),
        db: DbSession = Depends(db_session),
    ) -> CompleteUploadFileResponse:
        require_csrf(request)
        upload_file = db.get(orm.UploadFile, upload_file_id)
        if upload_file is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")
        upload_session, member = upload_session_for_user(
            db, upload_file.upload_session_id, auth.user.id
        )
        if upload_session.id != upload_file.upload_session_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")
        if upload_file.state == UploadState.COMPLETED.value:
            return CompleteUploadFileResponse(
                file=upload_file_response(upload_file, include_grant=False)
            )
        if upload_file.state in {UploadState.CANCELLED.value, UploadState.FAILED.value}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Upload is closed")

        now = datetime.now(UTC)
        upload_file.state = UploadState.VERIFYING.value
        upload_file.updated_at = now
        try:
            metadata = app.state.blob_store.stat(
                BlobRef(store_alias=upload_file.store_alias, object_key=upload_file.object_key)
            )
        except BlobNotFoundError as exc:
            upload_file.state = UploadState.FAILED.value
            upload_file.failed_at = now
            upload_file.error_message = "Uploaded object was not found"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded object was not found"
            ) from exc

        if metadata.size_bytes != upload_file.declared_byte_size:
            upload_file.state = UploadState.FAILED.value
            upload_file.failed_at = now
            upload_file.error_message = "Uploaded object size does not match declaration"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded object size does not match declaration",
            )

        media_item = orm.MediaItem(
            trip_id=upload_session.trip_id,
            contributor_member_id=member.id,
            media_type=MediaType.PHOTO.value,
            original_filename=upload_file.original_filename,
            declared_mime_type=upload_file.declared_mime_type,
            detected_mime_type=metadata.content_type,
            byte_size=metadata.size_bytes,
            original_store_alias=upload_file.store_alias,
            original_object_key=upload_file.object_key,
            sha256=metadata.checksum,
        )
        db.add(media_item)
        db.flush()
        upload_file.media_item_id = media_item.id
        upload_file.detected_mime_type = metadata.content_type
        upload_file.sha256 = metadata.checksum
        upload_file.state = UploadState.COMPLETED.value
        upload_file.transferred_at = now
        upload_file.verified_at = now
        upload_file.completed_at = now
        upload_file.updated_at = now
        db.add(
            orm.ProcessingJob(
                job_type=ProcessingJobType.INGEST_MEDIA.value,
                target_type=ProcessingTargetType.MEDIA_ITEM.value,
                target_id=media_item.id,
                idempotency_key=f"ingest-media:{media_item.id}",
            )
        )
        remaining = db.execute(
            select(func.count())
            .select_from(orm.UploadFile)
            .where(
                orm.UploadFile.upload_session_id == upload_session.id,
                orm.UploadFile.id != upload_file.id,
                orm.UploadFile.state != UploadState.COMPLETED.value,
            )
        ).scalar_one()
        if remaining == 0:
            upload_session.state = UploadState.COMPLETED.value
            upload_session.completed_at = now
        else:
            upload_session.state = UploadState.TRANSFERRING.value
        upload_session.updated_at = now
        db.commit()
        return CompleteUploadFileResponse(
            file=upload_file_response(upload_file, include_grant=False)
        )

    @app.delete("/upload-files/{upload_file_id}", status_code=status.HTTP_204_NO_CONTENT)
    def cancel_upload_file(
        upload_file_id: UUID,
        request: Request,
        auth: AuthenticatedUser = Depends(current_user),
        db: DbSession = Depends(db_session),
    ) -> Response:
        require_csrf(request)
        upload_file = db.get(orm.UploadFile, upload_file_id)
        if upload_file is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")
        upload_session_for_user(db, upload_file.upload_session_id, auth.user.id)
        if upload_file.state != UploadState.COMPLETED.value:
            now = datetime.now(UTC)
            upload_file.state = UploadState.CANCELLED.value
            upload_file.cancelled_at = now
            upload_file.updated_at = now
            app.state.blob_store.delete(
                BlobRef(store_alias=upload_file.store_alias, object_key=upload_file.object_key)
            )
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
