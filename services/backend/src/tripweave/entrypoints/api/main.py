# ruff: noqa: B008
import json
import os
import secrets
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import and_, delete, func, literal_column, or_, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from tripweave.adapters import orm
from tripweave.adapters.blob_store_factory import create_blob_store
from tripweave.adapters.database import check_database, create_database_engine, get_postgis_version
from tripweave.adapters.geocoder_factory import create_geocoder
from tripweave.adapters.local_blob_store import (
    BlobNotFoundError,
    BlobSizeExceededError,
    InvalidGrantError,
)
from tripweave.adapters.publication import PublicationError, blob_ref_from_manifest, load_manifest
from tripweave.adapters.reconstruction import MOMENT_GAP_MINUTES, reconstruct_trip
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
    EditOperationStatus,
    EditOperationType,
    InvitationStatus,
    MediaAssetType,
    MediaType,
    MediaVisibility,
    OriginalRetentionState,
    ProcessingJobState,
    ProcessingJobType,
    ProcessingState,
    ProcessingTargetType,
    ReviewItemStatus,
    RouteSource,
    ShareLinkStatus,
    StoryVersionState,
    SuggestionStatus,
    TripMemberRole,
    TripStatus,
    TripVisibility,
    UploadState,
)
from tripweave.domain.storage import (
    BlobRef,
    DownloadGrantRequest,
    UploadGrant,
    UploadGrantRequest,
    UploadTransport,
)
from tripweave.entrypoints.api.schemas import (
    AuthResponse,
    BlobRefResponse,
    CompleteUploadFileResponse,
    EditOperationRequest,
    EditOperationResponse,
    GuestMemberResponse,
    InvitationAcceptRequest,
    InvitationCreateRequest,
    InvitationPreviewResponse,
    InvitationResponse,
    InvitationsListResponse,
    LoginRequest,
    MediaAssetResponse,
    MediaItemResponse,
    MediaListResponse,
    MediaUpdateRequest,
    MemberResponse,
    MemberRosterResponse,
    MeResponse,
    PublicationResponse,
    PublicationsListResponse,
    PublicStoryResponse,
    ReconstructionDayResponse,
    ReconstructionLegResponse,
    ReconstructionMediaResponse,
    ReconstructionMomentResponse,
    ReconstructionResponse,
    ReconstructionRunResponse,
    ReconstructionStopResponse,
    RegisterRequest,
    ReviewItemResponse,
    ShareLinkResponse,
    SimilarityGroupResponse,
    SimilarityGroupsResponse,
    SimilarityMemberResponse,
    StoryPhotoProjectionResponse,
    StoryUpdateStatusResponse,
    StoryVersionResponse,
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

STORY_DRAFT_PROJECTION_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    user: orm.User
    session: orm.Session


@dataclass(frozen=True, slots=True)
class AuthenticatedGuest:
    member: orm.TripMember
    session: orm.GuestSession


@dataclass(frozen=True, slots=True)
class AuthenticatedActor:
    user: orm.User | None
    user_session: orm.Session | None
    guest_session: orm.GuestSession | None
    guest_member: orm.TripMember | None

    @property
    def is_guest(self) -> bool:
        return self.guest_member is not None


LOCAL_PUBLIC_API_BASE_URL = "http://localhost:8000"


def public_asset_base_url(settings: Settings, request_base_url: str) -> str:
    configured_base_url = settings.public_api_base_url.rstrip("/")
    parsed_configured = urlparse(configured_base_url)
    parsed_request = urlparse(request_base_url)
    configured_host = parsed_configured.hostname
    request_host = parsed_request.hostname
    configured_is_loopback = configured_host in {"localhost", "127.0.0.1", "::1"}
    request_is_loopback = request_host in {"localhost", "127.0.0.1", "::1"}
    if configured_is_loopback and not request_is_loopback:
        return request_base_url.rstrip("/")
    if settings.environment == "local" and configured_base_url == LOCAL_PUBLIC_API_BASE_URL:
        return request_base_url.rstrip("/")
    return configured_base_url


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
    app.state.invitation_rate_limiter = FixedWindowRateLimiter(
        max_attempts=resolved_settings.invitation_rate_limit_max_attempts,
        window_seconds=resolved_settings.action_rate_limit_window_seconds,
    )
    app.state.upload_registration_rate_limiter = FixedWindowRateLimiter(
        max_attempts=resolved_settings.upload_registration_rate_limit_max_attempts,
        window_seconds=resolved_settings.action_rate_limit_window_seconds,
    )
    app.state.publication_rate_limiter = FixedWindowRateLimiter(
        max_attempts=resolved_settings.publication_rate_limit_max_attempts,
        window_seconds=resolved_settings.action_rate_limit_window_seconds,
    )
    app.state.publication_manifest_cache = {}
    app.state.blob_store = create_blob_store(resolved_settings)
    app.state.geocoder = create_geocoder(resolved_settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_origin_regex=resolved_settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["content-type", "x-csrf-token", "x-request-id", "x-tripweave-actor"],
    )

    @app.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or secrets.token_hex(16)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response

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

    def optional_user(request: Request, db: DbSession) -> AuthenticatedUser | None:
        token = request.cookies.get(resolved_settings.session_cookie_name)
        if not token:
            return None
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
            return None
        user_session, user = result
        return AuthenticatedUser(user=user, session=user_session)

    def optional_guest(request: Request, db: DbSession) -> AuthenticatedGuest | None:
        token = request.cookies.get(resolved_settings.guest_session_cookie_name)
        if not token:
            return None
        now = datetime.now(UTC)
        result = db.execute(
            select(orm.GuestSession, orm.TripMember)
            .join(orm.TripMember, orm.TripMember.id == orm.GuestSession.member_id)
            .where(
                orm.GuestSession.token_hash == hash_token(token),
                orm.GuestSession.revoked_at.is_(None),
                orm.GuestSession.expires_at > now,
                orm.TripMember.removed_at.is_(None),
            )
        ).one_or_none()
        if result is None:
            return None
        guest_session, member = result
        return AuthenticatedGuest(member=member, session=guest_session)

    def current_actor(
        request: Request,
        db: DbSession = Depends(db_session),
    ) -> AuthenticatedActor:
        if request.headers.get("x-tripweave-actor") == "guest":
            guest = optional_guest(request, db)
            if guest is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
                )
            return AuthenticatedActor(
                user=None,
                user_session=None,
                guest_session=guest.session,
                guest_member=guest.member,
            )
        user = optional_user(request, db)
        if user is not None:
            return AuthenticatedActor(
                user=user.user,
                user_session=user.session,
                guest_session=None,
                guest_member=None,
            )
        guest = optional_guest(request, db)
        if guest is not None:
            return AuthenticatedActor(
                user=None,
                user_session=None,
                guest_session=guest.session,
                guest_member=guest.member,
            )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

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

    def set_guest_cookies(response: Response, session_token: str, csrf_token: str) -> None:
        response.set_cookie(
            resolved_settings.guest_session_cookie_name,
            session_token,
            httponly=True,
            max_age=resolved_settings.guest_session_lifetime_seconds,
            secure=resolved_settings.secure_cookies,
            samesite="lax",
            path="/",
        )
        response.set_cookie(
            resolved_settings.csrf_cookie_name,
            csrf_token,
            httponly=False,
            max_age=resolved_settings.guest_session_lifetime_seconds,
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

    def clear_guest_cookies(response: Response) -> None:
        response.delete_cookie(
            resolved_settings.guest_session_cookie_name,
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

    def rate_limit_action(request: Request, limiter_name: str, action: str, actor_key: str) -> None:
        client_host = request.client.host if request.client else "unknown"
        limiter = getattr(app.state, limiter_name)
        key = f"{action}:{client_host}:{actor_key}"
        if not limiter.allow(key):
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

    @app.get("/ops/local-mvp")
    def local_mvp_operations(
        _auth: AuthenticatedUser = Depends(current_user),
        db: DbSession = Depends(db_session),
    ) -> dict[str, object]:
        now = datetime.now(UTC)
        job_rows = db.execute(
            select(orm.ProcessingJob.state, func.count())
            .group_by(orm.ProcessingJob.state)
            .order_by(orm.ProcessingJob.state)
        ).all()
        media_rows = db.execute(
            select(orm.MediaItem.processing_state, func.count())
            .where(orm.MediaItem.deleted_at.is_(None))
            .group_by(orm.MediaItem.processing_state)
            .order_by(orm.MediaItem.processing_state)
        ).all()
        upload_rows = db.execute(
            select(orm.UploadFile.state, func.count())
            .group_by(orm.UploadFile.state)
            .order_by(orm.UploadFile.state)
        ).all()
        share_rows = db.execute(
            select(orm.ShareLink.status, func.count())
            .group_by(orm.ShareLink.status)
            .order_by(orm.ShareLink.status)
        ).all()
        review_rows = db.execute(
            select(orm.ReviewItem.status, func.count())
            .group_by(orm.ReviewItem.status)
            .order_by(orm.ReviewItem.status)
        ).all()
        recent_failures = db.execute(
            select(
                orm.ProcessingJob.id,
                orm.ProcessingJob.job_type,
                orm.ProcessingJob.target_type,
                orm.ProcessingJob.state,
                orm.ProcessingJob.error_code,
                orm.ProcessingJob.error_message,
                orm.ProcessingJob.attempts,
                orm.ProcessingJob.max_attempts,
                orm.ProcessingJob.finished_at,
                orm.ProcessingJob.created_at,
            )
            .where(orm.ProcessingJob.state == ProcessingJobState.FAILED.value)
            .order_by(
                orm.ProcessingJob.finished_at.desc().nullslast(),
                orm.ProcessingJob.created_at.desc(),
            )
            .limit(10)
        ).all()
        storage = local_storage_usage(resolved_settings)
        trip_count = db.scalar(select(func.count()).select_from(orm.Trip)) or 0
        user_count = db.scalar(select(func.count()).select_from(orm.User)) or 0
        member_count = db.scalar(select(func.count()).select_from(orm.TripMember)) or 0
        active_share_count = (
            db.scalar(
                select(func.count())
                .select_from(orm.ShareLink)
                .where(orm.ShareLink.status == ShareLinkStatus.ACTIVE.value)
            )
            or 0
        )
        worker = worker_status(resolved_settings)
        storage_secret_is_placeholder = (
            resolved_settings.storage_signing_secret == "local-development-upload-signing-secret"
            or resolved_settings.storage_signing_secret.startswith("replace-with-")
        )
        return {
            "generatedAt": now.isoformat(),
            "environment": {
                "name": resolved_settings.environment,
                "secureCookies": resolved_settings.secure_cookies,
                "allowedWebOrigins": resolved_settings.cors_origins,
                "publicApiBaseUrl": resolved_settings.public_api_base_url,
                "storageAliases": sorted(resolved_settings.store_aliases),
            },
            "counts": {
                "users": int(user_count),
                "trips": int(trip_count),
                "members": int(member_count),
                "activeShareLinks": int(active_share_count),
            },
            "jobStates": {str(state): int(count) for state, count in job_rows},
            "mediaStates": {str(state): int(count) for state, count in media_rows},
            "uploadStates": {str(state): int(count) for state, count in upload_rows},
            "reviewStates": {str(state): int(count) for state, count in review_rows},
            "shareLinkStates": {str(state): int(count) for state, count in share_rows},
            "recentFailures": [
                {
                    "id": str(job_id),
                    "jobType": job_type,
                    "targetType": target_type,
                    "state": state,
                    "errorCode": error_code,
                    "safeMessage": error_message,
                    "attempts": attempts,
                    "maxAttempts": max_attempts,
                    "finishedAt": finished_at.isoformat() if finished_at else None,
                    "createdAt": created_at.isoformat(),
                }
                for (
                    job_id,
                    job_type,
                    target_type,
                    state,
                    error_code,
                    error_message,
                    attempts,
                    max_attempts,
                    finished_at,
                    created_at,
                ) in recent_failures
            ],
            "worker": worker,
            "storage": storage,
            "limits": {
                "maxFilesPerTrip": resolved_settings.upload_max_files_per_trip,
                "maxFileBytes": resolved_settings.upload_max_file_bytes,
                "maxTripBytes": resolved_settings.upload_max_trip_bytes,
                "allowedExtensions": sorted(resolved_settings.allowed_upload_extensions),
                "allowedMimeTypes": sorted(resolved_settings.allowed_upload_mime_types),
                "workerConcurrency": resolved_settings.worker_concurrency,
            },
            "warnings": {
                "storageSoftLimit": storage["totalBytes"]
                >= resolved_settings.upload_max_trip_bytes,
                "workerStale": not worker["ok"],
                "usingDefaultStorageSigningSecret": storage_secret_is_placeholder,
            },
            "softLimitWarning": storage["totalBytes"] >= resolved_settings.upload_max_trip_bytes,
        }

    def member_for_trip(db: DbSession, trip_id: UUID, user_id: UUID) -> orm.TripMember | None:
        return db.execute(
            select(orm.TripMember).where(
                orm.TripMember.trip_id == trip_id,
                orm.TripMember.user_id == user_id,
                orm.TripMember.removed_at.is_(None),
            )
        ).scalar_one_or_none()

    def member_for_actor(
        db: DbSession, trip_id: UUID, actor: AuthenticatedActor
    ) -> orm.TripMember | None:
        if actor.user is not None:
            return member_for_trip(db, trip_id, actor.user.id)
        if (
            actor.guest_member is not None
            and actor.guest_member.trip_id == trip_id
            and actor.guest_member.removed_at is None
        ):
            return actor.guest_member
        return None

    def require_member_for_actor(
        db: DbSession, trip_id: UUID, actor: AuthenticatedActor
    ) -> orm.TripMember:
        member = member_for_actor(db, trip_id, actor)
        if member is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
        return member

    def require_owner_member(db: DbSession, trip_id: UUID, user_id: UUID) -> orm.TripMember:
        member = member_for_trip(db, trip_id, user_id)
        if member is None or member.role != TripMemberRole.OWNER.value:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
        return member

    def trip_response(trip: orm.Trip, role: str, member_id: UUID) -> TripResponse:
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
            memberId=member_id,
            createdAt=trip.created_at,
            updatedAt=trip.updated_at,
        )

    def invitation_url(request: Request, token: str) -> str:
        origin = request.headers.get("origin")
        if resolved_settings.web_origin_is_allowed(origin):
            return f"{origin}/invite/{token}"
        return f"http://localhost:3000/invite/{token}"

    def share_url(request: Request, token: str) -> str:
        origin = request.headers.get("origin")
        if resolved_settings.web_origin_is_allowed(origin):
            return f"{origin}/story/{token}"
        return f"http://localhost:3000/story/{token}"

    def invitation_response(
        invitation: orm.TripInvitation, invite_url: str | None = None
    ) -> InvitationResponse:
        status_value = invitation.status
        if (
            invitation.status == InvitationStatus.PENDING.value
            and invitation.expires_at <= datetime.now(UTC)
        ):
            status_value = InvitationStatus.EXPIRED.value
        return InvitationResponse(
            id=invitation.id,
            tripId=invitation.trip_id,
            role=invitation.role,
            status=status_value,
            expiresAt=invitation.expires_at,
            useCount=invitation.use_count,
            maxUses=invitation.max_uses,
            revokedAt=invitation.revoked_at,
            acceptedAt=invitation.accepted_at,
            inviteUrl=invite_url,
        )

    def story_version_response(version: orm.StoryVersion) -> StoryVersionResponse:
        return StoryVersionResponse(
            id=version.id,
            tripId=version.trip_id,
            versionNumber=version.version_number,
            state=version.state,
            title=version.title,
            publishedAt=version.published_at,
            errorMessage=version.error_message,
        )

    def share_link_response(link: orm.ShareLink, url: str | None = None) -> ShareLinkResponse:
        status_value = link.status
        if (
            status_value == ShareLinkStatus.ACTIVE.value
            and link.expires_at is not None
            and link.expires_at <= datetime.now(UTC)
        ):
            status_value = ShareLinkStatus.EXPIRED.value
        return ShareLinkResponse(
            id=link.id,
            tripId=link.trip_id,
            storyVersionId=link.story_version_id,
            status=status_value,
            expiresAt=link.expires_at,
            revokedAt=link.revoked_at,
            shareUrl=url,
        )

    def next_story_version_number(db: DbSession, trip_id: UUID) -> int:
        current = db.scalar(
            select(func.max(orm.StoryVersion.version_number)).where(
                orm.StoryVersion.trip_id == trip_id
            )
        )
        return int(current or 0) + 1

    def active_share_link_for_trip(db: DbSession, trip_id: UUID) -> orm.ShareLink | None:
        return db.execute(
            select(orm.ShareLink)
            .where(
                orm.ShareLink.trip_id == trip_id,
                orm.ShareLink.status == ShareLinkStatus.ACTIVE.value,
                orm.ShareLink.revoked_at.is_(None),
            )
            .order_by(orm.ShareLink.created_at.desc(), orm.ShareLink.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def latest_reconstruction_run_id_or_none(db: DbSession, trip_id: UUID) -> UUID | None:
        return db.scalar(
            select(orm.ReconstructionRun.id)
            .where(
                orm.ReconstructionRun.trip_id == trip_id,
                orm.ReconstructionRun.state == "succeeded",
            )
            .order_by(orm.ReconstructionRun.created_at.desc(), orm.ReconstructionRun.id.desc())
            .limit(1)
        )

    def validate_publishable(db: DbSession, trip_id: UUID) -> UUID:
        run_id = latest_reconstruction_run_id_or_none(db, trip_id)
        if run_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Run reconstruction before publishing",
            )
        publishable_media_count = db.scalar(
            select(func.count())
            .select_from(orm.MediaItem)
            .where(
                orm.MediaItem.trip_id == trip_id,
                orm.MediaItem.processing_state == ProcessingState.READY.value,
                orm.MediaItem.deleted_at.is_(None),
                orm.MediaItem.include_in_story.is_(True),
                orm.MediaItem.visibility == MediaVisibility.STORY.value,
            )
        )
        if int(publishable_media_count or 0) == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Mark at least one ready media item as Story before publishing",
            )
        assigned_media_count = db.scalar(
            select(func.count(func.distinct(orm.MomentMedia.media_item_id)))
            .join(orm.MediaItem, orm.MediaItem.id == orm.MomentMedia.media_item_id)
            .where(
                orm.MomentMedia.trip_id == trip_id,
                or_(
                    orm.MomentMedia.reconstruction_run_id == run_id,
                    orm.MomentMedia.user_locked.is_(True),
                ),
                orm.MediaItem.processing_state == ProcessingState.READY.value,
                orm.MediaItem.deleted_at.is_(None),
                orm.MediaItem.include_in_story.is_(True),
                orm.MediaItem.visibility == MediaVisibility.STORY.value,
            )
        )
        if int(assigned_media_count or 0) == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Run reconstruction after choosing story media",
            )
        missing_derivative_count = db.scalar(
            select(func.count())
            .select_from(orm.MediaItem)
            .where(
                orm.MediaItem.trip_id == trip_id,
                orm.MediaItem.processing_state == ProcessingState.READY.value,
                orm.MediaItem.deleted_at.is_(None),
                orm.MediaItem.include_in_story.is_(True),
                orm.MediaItem.visibility == MediaVisibility.STORY.value,
                or_(
                    ~orm.MediaItem.assets.any(
                        and_(
                            orm.MediaAsset.asset_type == MediaAssetType.THUMBNAIL.value,
                            orm.MediaAsset.metadata_stripped.is_(True),
                        )
                    ),
                    ~orm.MediaItem.assets.any(
                        and_(
                            orm.MediaAsset.asset_type == MediaAssetType.DISPLAY.value,
                            orm.MediaAsset.metadata_stripped.is_(True),
                        )
                    ),
                ),
            )
        )
        if int(missing_derivative_count or 0) > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Wait for media processing to finish before publishing",
            )
        return run_id

    def active_share_link_for_token(db: DbSession, token: str) -> orm.ShareLink:
        link = db.execute(
            select(orm.ShareLink).where(orm.ShareLink.token_hash == hash_token(token))
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        if (
            link is None
            or link.revoked_at is not None
            or link.status != ShareLinkStatus.ACTIVE.value
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story unavailable")
        if link.expires_at is not None and link.expires_at <= now:
            link.status = ShareLinkStatus.EXPIRED.value
            db.commit()
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Story link expired")
        if link.story_version_id is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Story is publishing"
            )
        link.last_accessed_at = now
        db.flush()
        return link

    def public_story_response(
        request: Request,
        token: str,
        link: orm.ShareLink,
        version: orm.StoryVersion,
        manifest: dict[str, object],
    ) -> PublicStoryResponse:
        asset_urls = public_asset_urls(request, token, manifest)
        story = reconstruction_from_manifest(manifest, asset_urls)
        trip = dict_or_empty(manifest.get("trip"))
        return PublicStoryResponse(
            version=story_version_response(version),
            story=story,
            trip=trip,
            participants=list_of_dicts(manifest.get("participants")),
        )

    def public_asset_urls(
        request: Request, token: str, manifest: dict[str, object]
    ) -> dict[str, str]:
        assets = manifest.get("assets")
        if not isinstance(assets, list):
            return {}
        request_base_url = str(request.base_url).rstrip("/")
        public_base_url = public_asset_base_url(resolved_settings, request_base_url)
        return {
            str(asset["id"]): f"{public_base_url}/public/shares/{token}/assets/{asset['id']}"
            for asset in assets
            if isinstance(asset, dict) and isinstance(asset.get("id"), str)
        }

    def public_asset_for_id(manifest: dict[str, object], asset_id: str) -> dict[str, object]:
        assets = manifest.get("assets")
        if not isinstance(assets, list):
            raise PublicationError("asset_not_found", "Asset not found")
        for asset in assets:
            if isinstance(asset, dict) and asset.get("id") == asset_id:
                return dict(asset)
        raise PublicationError("asset_not_found", "Asset not found")

    def blob_ref_for_public_asset(asset: dict[str, object]) -> BlobRef:
        blob_ref_payload = asset.get("blobRef")
        if not isinstance(blob_ref_payload, dict):
            raise PublicationError("publication_invalid", "Story asset is invalid")
        blob_ref = blob_ref_from_manifest(blob_ref_payload)
        checksum = blob_ref_payload.get("checksum")
        size_bytes = blob_ref_payload.get("sizeBytes")
        content_type = blob_ref_payload.get("contentType") or asset.get("mimeType")
        return BlobRef(
            store_alias=blob_ref.store_alias,
            object_key=blob_ref.object_key,
            checksum_algorithm="sha256" if isinstance(checksum, str) else None,
            checksum=checksum if isinstance(checksum, str) else None,
            size_bytes=size_bytes if isinstance(size_bytes, int) else None,
            content_type=content_type if isinstance(content_type, str) else None,
        )

    def cached_public_manifest(version: orm.StoryVersion) -> dict[str, object]:
        cache_key = (
            str(version.id),
            version.manifest_store_alias,
            version.manifest_object_key,
            version.manifest_checksum,
        )
        cache: dict[tuple[str, str | None, str | None, str | None], dict[str, object]] = (
            app.state.publication_manifest_cache
        )
        cached = cache.get(cache_key)
        if cached is None:
            cached = load_manifest(app.state.blob_store, version)
            cache[cache_key] = cached
            if len(cache) > 64:
                oldest_key = next(iter(cache))
                cache.pop(oldest_key, None)
        manifest_copy = json.loads(json.dumps(cached))
        return dict(manifest_copy) if isinstance(manifest_copy, dict) else {}

    def reconstruction_from_manifest(
        manifest: dict[str, object], asset_urls: dict[str, str]
    ) -> ReconstructionResponse:
        days_payload = manifest.get("days")
        days_list = days_payload if isinstance(days_payload, list) else []
        days: list[ReconstructionDayResponse] = []
        for day_payload in days_list:
            if not isinstance(day_payload, dict):
                continue
            stops: list[ReconstructionStopResponse] = []
            for stop_payload in list_payload(day_payload, "stops"):
                moments: list[ReconstructionMomentResponse] = []
                for moment_payload in list_payload(stop_payload, "moments"):
                    media = [
                        ReconstructionMediaResponse(
                            id=UUID(str(media_payload["id"])),
                            filename=None,
                            capturedAt=parse_datetime(media_payload.get("capturedAt")),
                            capturedAtLocal=parse_datetime(media_payload.get("capturedAtLocal")),
                            latitude=number_or_none(media_payload.get("latitude")),
                            longitude=number_or_none(media_payload.get("longitude")),
                            contributorMemberId=UUID(str(media_payload["contributorMemberId"])),
                            contributor=str(media_payload.get("contributor") or "Traveler"),
                            thumbnailUrl=asset_urls.get(str(media_payload.get("thumbnailAssetId"))),
                            previewUrl=asset_urls.get(str(media_payload.get("previewAssetId"))),
                        )
                        for media_payload in list_payload(moment_payload, "media")
                        if isinstance(media_payload.get("id"), str)
                        and isinstance(media_payload.get("contributorMemberId"), str)
                    ]
                    moments.append(
                        ReconstructionMomentResponse(
                            id=UUID(str(moment_payload["id"])),
                            position=int_or_zero(moment_payload.get("position")),
                            title=str(moment_payload["title"])
                            if moment_payload.get("title") is not None
                            else None,
                            startsAt=parse_datetime_required(moment_payload.get("startsAt")),
                            endsAt=parse_datetime_required(moment_payload.get("endsAt")),
                            startsAtLocal=parse_datetime(moment_payload.get("startsAtLocal")),
                            endsAtLocal=parse_datetime(moment_payload.get("endsAtLocal")),
                            mediaCount=int_or_zero(
                                moment_payload.get("mediaCount"), fallback=len(media)
                            ),
                            contributorCount=int_or_zero(moment_payload.get("contributorCount")),
                            media=media,
                        )
                    )
                stops.append(
                    ReconstructionStopResponse(
                        id=UUID(str(stop_payload["id"])),
                        position=int_or_zero(stop_payload.get("position")),
                        title=str(stop_payload["title"])
                        if stop_payload.get("title") is not None
                        else None,
                        note=str(stop_payload["note"])
                        if stop_payload.get("note") is not None
                        else None,
                        startsAt=parse_datetime_required(stop_payload.get("startsAt")),
                        endsAt=parse_datetime_required(stop_payload.get("endsAt")),
                        startsAtLocal=parse_datetime(stop_payload.get("startsAtLocal")),
                        endsAtLocal=parse_datetime(stop_payload.get("endsAtLocal")),
                        placeName=str(stop_payload["placeName"])
                        if stop_payload.get("placeName") is not None
                        else None,
                        latitude=number_or_none(stop_payload.get("latitude")),
                        longitude=number_or_none(stop_payload.get("longitude")),
                        mediaCount=int_or_zero(stop_payload.get("mediaCount")),
                        contributorCount=int_or_zero(stop_payload.get("contributorCount")),
                        moments=moments,
                    )
                )
            legs = [
                ReconstructionLegResponse(
                    id=UUID(str(leg_payload["id"])),
                    fromStopId=UUID(str(leg_payload["fromStopId"])),
                    toStopId=UUID(str(leg_payload["toStopId"])),
                    routeSource=str(leg_payload.get("routeSource") or "photo_inferred"),
                    geometry=dict_or_none(leg_payload.get("geometry")),
                )
                for leg_payload in list_payload(day_payload, "legs")
                if isinstance(leg_payload.get("id"), str)
                and isinstance(leg_payload.get("fromStopId"), str)
                and isinstance(leg_payload.get("toStopId"), str)
            ]
            days.append(
                ReconstructionDayResponse(
                    id=UUID(str(day_payload["id"])),
                    date=date.fromisoformat(str(day_payload["date"])),
                    position=int_or_zero(day_payload.get("position")),
                    title=str(day_payload["title"])
                    if day_payload.get("title") is not None
                    else None,
                    note=str(day_payload["note"]) if day_payload.get("note") is not None else None,
                    stops=stops,
                    legs=legs,
                )
            )
        published_at = parse_datetime(str(manifest.get("publishedAt")))
        return ReconstructionResponse(
            latestRun=ReconstructionRunResponse(
                id=UUID(str(manifest["storyVersionId"])),
                state="published",
                algorithmVersion=str(manifest.get("algorithmVersion") or "publication.v1"),
                summary={"versionNumber": manifest.get("versionNumber")},
                startedAt=published_at or datetime.now(UTC),
                finishedAt=published_at,
            ),
            days=days,
            reviewItems=[],
            storyUpdate=StoryUpdateStatusResponse(
                needsUpdate=False,
                unassignedReadyMediaCount=0,
                readyMediaCount=0,
                storyMediaCount=0,
            ),
        )

    def list_payload(payload: dict[str, object], key: str) -> list[dict[str, object]]:
        value = payload.get(key)
        if not isinstance(value, list):
            return []
        return [dict(item) for item in value if isinstance(item, dict)]

    def parse_datetime(value: object) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        return datetime.fromisoformat(value)

    def parse_datetime_required(value: object) -> datetime:
        parsed = parse_datetime(value)
        if parsed is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Story is unavailable"
            )
        return parsed

    def number_or_none(value: object) -> float | None:
        return float(value) if isinstance(value, int | float) else None

    def int_or_zero(value: object, fallback: int = 0) -> int:
        return value if isinstance(value, int) else fallback

    def dict_or_empty(value: object) -> dict[str, object]:
        return dict(value) if isinstance(value, dict) else {}

    def dict_or_none(value: object) -> dict[str, object] | None:
        return dict(value) if isinstance(value, dict) else None

    def list_of_dicts(value: object) -> list[dict[str, object]]:
        if not isinstance(value, list):
            return []
        return [dict(item) for item in value if isinstance(item, dict)]

    def member_response(member: orm.TripMember) -> MemberResponse:
        return MemberResponse(
            id=member.id,
            displayName=member.display_name,
            role=member.role,
            joinedAt=member.joined_at,
            removedAt=member.removed_at,
            isGuest=member.user_id is None,
        )

    def active_invitation_for_token(db: DbSession, token: str) -> orm.TripInvitation:
        invitation = db.execute(
            select(orm.TripInvitation).where(orm.TripInvitation.token_hash == hash_token(token))
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        if invitation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found"
            )
        if invitation.revoked_at is not None or invitation.status == InvitationStatus.REVOKED.value:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found"
            )
        if invitation.expires_at <= now:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found"
            )
        return invitation

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
        return trip_response(trip, member.role, member.id)

    @app.post(
        "/trips/{trip_id}/invitations",
        response_model=InvitationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_invitation(
        trip_id: UUID,
        payload: InvitationCreateRequest,
        request: Request,
        auth: AuthenticatedUser = Depends(current_user),
        db: DbSession = Depends(db_session),
    ) -> InvitationResponse:
        require_csrf(request)
        owner_member = require_owner_member(db, trip_id, auth.user.id)
        rate_limit_action(
            request,
            "invitation_rate_limiter",
            "create-invitation",
            f"{trip_id}:{owner_member.id}",
        )
        trip = db.get(orm.Trip, trip_id)
        if trip is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        invitation = orm.TripInvitation(
            trip_id=trip_id,
            email=None,
            role=TripMemberRole.CONTRIBUTOR.value,
            token_hash=hash_token(token),
            status=InvitationStatus.PENDING.value,
            expires_at=now
            + timedelta(
                seconds=payload.expires_in_seconds or resolved_settings.invitation_lifetime_seconds
            ),
            max_uses=1,
            use_count=0,
        )
        db.add(invitation)
        db.commit()
        return invitation_response(invitation, invitation_url(request, token))

    @app.get("/trips/{trip_id}/invitations", response_model=InvitationsListResponse)
    def list_invitations(
        trip_id: UUID,
        auth: AuthenticatedUser = Depends(current_user),
        db: DbSession = Depends(db_session),
    ) -> InvitationsListResponse:
        require_owner_member(db, trip_id, auth.user.id)
        invitations = db.scalars(
            select(orm.TripInvitation)
            .where(orm.TripInvitation.trip_id == trip_id)
            .order_by(orm.TripInvitation.created_at.desc(), orm.TripInvitation.id)
        ).all()
        return InvitationsListResponse(
            invitations=[invitation_response(invitation) for invitation in invitations]
        )

    @app.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
    def revoke_invitation(
        invitation_id: UUID,
        request: Request,
        auth: AuthenticatedUser = Depends(current_user),
        db: DbSession = Depends(db_session),
    ) -> Response:
        require_csrf(request)
        invitation = db.get(orm.TripInvitation, invitation_id)
        if invitation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found"
            )
        require_owner_member(db, invitation.trip_id, auth.user.id)
        invitation.status = InvitationStatus.REVOKED.value
        invitation.revoked_at = datetime.now(UTC)
        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/invitations/{token}", response_model=InvitationPreviewResponse)
    def preview_invitation(
        token: str, db: DbSession = Depends(db_session)
    ) -> InvitationPreviewResponse:
        invitation = active_invitation_for_token(db, token)
        trip = db.get(orm.Trip, invitation.trip_id)
        if trip is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found"
            )
        return InvitationPreviewResponse(
            tripId=trip.id,
            title=trip.title,
            role=invitation.role,
            expiresAt=invitation.expires_at,
            status=invitation.status,
        )

    @app.post("/invitations/{token}/accept", response_model=GuestMemberResponse)
    def accept_invitation(
        token: str,
        payload: InvitationAcceptRequest,
        request: Request,
        auth: AuthenticatedUser = Depends(current_user),
        db: DbSession = Depends(db_session),
    ) -> GuestMemberResponse:
        require_csrf(request)
        invitation = active_invitation_for_token(db, token)
        now = datetime.now(UTC)
        member = (
            db.get(orm.TripMember, invitation.accepted_member_id)
            if invitation.accepted_member_id is not None
            else None
        )
        if member is None:
            member = member_for_trip(db, invitation.trip_id, auth.user.id)
            if member is None:
                if invitation.use_count >= invitation.max_uses:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found"
                    )
                member = orm.TripMember(
                    trip_id=invitation.trip_id,
                    user_id=auth.user.id,
                    role=invitation.role,
                    display_name=(payload.display_name or auth.user.display_name).strip(),
                    joined_at=now,
                )
                db.add(member)
                db.flush()
            invitation.accepted_member_id = member.id
            invitation.accepted_at = now
            invitation.use_count += 1
            invitation.status = InvitationStatus.ACCEPTED.value
        elif member.removed_at is not None or member.user_id != auth.user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found"
            )
        csrf_token = request.cookies.get(resolved_settings.csrf_cookie_name, "")
        db.commit()
        return GuestMemberResponse(
            id=member.id,
            tripId=member.trip_id,
            displayName=member.display_name,
            role=member.role,
            csrfToken=csrf_token,
        )

    @app.get("/guest/me", response_model=GuestMemberResponse)
    def guest_me(
        request: Request,
        guest: AuthenticatedActor = Depends(current_actor),
    ) -> GuestMemberResponse:
        if guest.guest_member is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )
        csrf_token = request.cookies.get(resolved_settings.csrf_cookie_name, "")
        return GuestMemberResponse(
            id=guest.guest_member.id,
            tripId=guest.guest_member.trip_id,
            displayName=guest.guest_member.display_name,
            role=guest.guest_member.role,
            csrfToken=csrf_token,
        )

    @app.get("/trips/{trip_id}/members", response_model=MemberRosterResponse)
    def list_members(
        trip_id: UUID,
        auth: AuthenticatedUser = Depends(current_user),
        db: DbSession = Depends(db_session),
    ) -> MemberRosterResponse:
        require_owner_member(db, trip_id, auth.user.id)
        members = db.scalars(
            select(orm.TripMember)
            .where(orm.TripMember.trip_id == trip_id)
            .order_by(orm.TripMember.joined_at, orm.TripMember.id)
        ).all()
        return MemberRosterResponse(members=[member_response(member) for member in members])

    @app.delete("/trip-members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
    def remove_member(
        member_id: UUID,
        request: Request,
        auth: AuthenticatedUser = Depends(current_user),
        db: DbSession = Depends(db_session),
    ) -> Response:
        require_csrf(request)
        member = db.get(orm.TripMember, member_id)
        if member is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
        require_owner_member(db, member.trip_id, auth.user.id)
        if member.role == TripMemberRole.OWNER.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove owner"
            )
        now = datetime.now(UTC)
        member.removed_at = now
        for session in db.scalars(
            select(orm.GuestSession).where(
                orm.GuestSession.member_id == member.id,
                orm.GuestSession.revoked_at.is_(None),
            )
        ):
            session.revoked_at = now
        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/trips", response_model=TripsListResponse)
    def list_trips(
        auth: AuthenticatedUser = Depends(current_user),
        db: DbSession = Depends(db_session),
    ) -> TripsListResponse:
        rows = db.execute(
            select(orm.Trip, orm.TripMember.role, orm.TripMember.id)
            .join(orm.TripMember, orm.TripMember.trip_id == orm.Trip.id)
            .where(
                orm.TripMember.user_id == auth.user.id,
                orm.TripMember.removed_at.is_(None),
            )
            .order_by(orm.Trip.created_at.desc(), orm.Trip.id)
        ).all()
        return TripsListResponse(
            trips=[trip_response(trip, role, member_id) for trip, role, member_id in rows]
        )

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
        return trip_response(trip, member.role, member.id)

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
        return trip_response(trip, member.role, member.id)

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

    def media_asset_response(asset: orm.MediaAsset) -> MediaAssetResponse:
        download_url: str | None = None
        try:
            download_url = app.state.blob_store.create_download_grant(
                DownloadGrantRequest(blob_ref=blob_ref_for_media_asset(asset))
            ).url
        except BlobNotFoundError:
            download_url = None
        return MediaAssetResponse(
            id=asset.id,
            assetType=asset.asset_type,
            width=asset.width,
            height=asset.height,
            mimeType=asset.mime_type,
            downloadUrl=download_url,
        )

    def blob_ref_for_media_asset(asset: orm.MediaAsset) -> BlobRef:
        return BlobRef(
            store_alias=asset.store_alias,
            object_key=asset.object_key,
            checksum_algorithm="sha256" if asset.checksum else None,
            checksum=asset.checksum,
            size_bytes=asset.byte_size,
            content_type=asset.mime_type,
        )

    def media_error_for(db: DbSession, media_item_id: UUID) -> str | None:
        job = db.execute(
            select(orm.ProcessingJob)
            .where(
                orm.ProcessingJob.target_id == media_item_id,
                orm.ProcessingJob.target_type == ProcessingTargetType.MEDIA_ITEM.value,
                orm.ProcessingJob.job_type == ProcessingJobType.INGEST_MEDIA.value,
            )
            .order_by(orm.ProcessingJob.created_at.desc(), orm.ProcessingJob.id)
            .limit(1)
        ).scalar_one_or_none()
        if job is None or job.state != "failed":
            return None
        return job.error_message

    def media_item_response(
        db: DbSession,
        media_item: orm.MediaItem,
        contributor: orm.TripMember,
        group_summary: dict[str, object] | None = None,
        *,
        can_update_visibility: bool = False,
    ) -> MediaItemResponse:
        thumbnail = next(
            (asset for asset in media_item.assets if asset.asset_type == "thumbnail"),
            None,
        )
        preview = next(
            (asset for asset in media_item.assets if asset.asset_type == "display"),
            None,
        )
        dimensions = media_item.original_metadata_json.get("dimensions", {})
        width = dimensions.get("width") if isinstance(dimensions, dict) else None
        height = dimensions.get("height") if isinstance(dimensions, dict) else None
        group_id = group_summary.get("group_id") if group_summary else None
        representative_id = (
            group_summary.get("representative_media_item_id") if group_summary else None
        )
        member_count = group_summary.get("member_count", 1) if group_summary else 1
        group_type = group_summary.get("group_type") if group_summary else None
        return MediaItemResponse(
            id=media_item.id,
            filename=media_item.original_filename,
            processingState=media_item.processing_state,
            errorMessage=media_error_for(db, media_item.id),
            originalRetentionState=media_item.original_retention_state,
            originalDeletedAt=media_item.original_deleted_at,
            visibility=media_item.visibility,
            includeInStory=media_item.include_in_story,
            canUpdateVisibility=can_update_visibility,
            capturedAt=media_item.effective_captured_at_utc
            or media_item.original_captured_at_utc
            or media_item.original_captured_at_local,
            gpsPresent=media_item.effective_location is not None
            or media_item.original_location is not None,
            width=width if isinstance(width, int) else None,
            height=height if isinstance(height, int) else None,
            contributor=contributor.display_name,
            contributorMemberId=contributor.id,
            thumbnail=media_asset_response(thumbnail) if thumbnail is not None else None,
            preview=media_asset_response(preview) if preview is not None else None,
            similarityGroupId=group_id if isinstance(group_id, UUID) else None,
            similarityGroupCount=member_count if isinstance(member_count, int) else 1,
            similarityGroupType=group_type if isinstance(group_type, str) else None,
            isSimilarityRepresentative=bool(group_summary.get("is_representative"))
            if group_summary
            else False,
            representativeMediaItemId=representative_id
            if isinstance(representative_id, UUID)
            else None,
        )

    def actor_can_update_media_visibility(
        media_item: orm.MediaItem,
        contributor: orm.TripMember,
        member: orm.TripMember,
        actor: AuthenticatedActor,
    ) -> bool:
        if media_item.contributor_member_id == member.id:
            return True
        return (
            actor.user is not None
            and contributor.user_id is not None
            and contributor.user_id == actor.user.id
        )

    def similarity_summary_by_media(db: DbSession, trip_id: UUID) -> dict[UUID, dict[str, object]]:
        rows = db.execute(
            select(orm.SimilarityGroup, orm.SimilarityGroupMember)
            .join(
                orm.SimilarityGroupMember,
                orm.SimilarityGroupMember.similarity_group_id == orm.SimilarityGroup.id,
            )
            .where(orm.SimilarityGroup.trip_id == trip_id)
        ).all()
        return {
            member.media_item_id: {
                "group_id": group.id,
                "member_count": group.member_count,
                "group_type": group.group_type,
                "is_representative": member.is_representative,
                "representative_media_item_id": group.representative_media_item_id,
            }
            for group, member in rows
        }

    def media_local_capture(media_item: orm.MediaItem) -> datetime | None:
        if media_item.original_captured_at_local is not None:
            return media_item.original_captured_at_local
        captured_at_utc = (
            media_item.effective_captured_at_utc or media_item.original_captured_at_utc
        )
        if captured_at_utc is None or media_item.original_utc_offset_minutes is None:
            return None
        return (
            captured_at_utc + timedelta(minutes=media_item.original_utc_offset_minutes)
        ).replace(tzinfo=None)

    def payload_uuid(payload: dict[str, object], key: str) -> UUID:
        value = payload.get(key)
        if not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{key} is required"
            )
        try:
            return UUID(value)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{key} is invalid"
            ) from exc

    def payload_str(payload: dict[str, object], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{key} is required"
            )
        return value

    def payload_optional_note(payload: dict[str, object]) -> str | None:
        value = payload.get("note")
        if value is None:
            return None
        if not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="note is invalid"
            )
        note = value.strip()
        return note or None

    def json_value(value: object) -> object:
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    def record_values(record: object, fields: list[str]) -> dict[str, object]:
        return {field: json_value(getattr(record, field)) for field in fields}

    def expected_fresh(record: object, expected_updated_at: datetime | None) -> None:
        if expected_updated_at is None:
            return
        current = getattr(record, "updated_at", None)
        if not isinstance(current, datetime) or current != expected_updated_at:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stale edit target")

    def latest_run_for_trip(db: DbSession, trip_id: UUID) -> orm.ReconstructionRun:
        run = db.execute(
            select(orm.ReconstructionRun)
            .where(orm.ReconstructionRun.trip_id == trip_id)
            .order_by(orm.ReconstructionRun.created_at.desc(), orm.ReconstructionRun.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Run reconstruction first"
            )
        return run

    def correction_generated(run: orm.ReconstructionRun) -> dict[str, object]:
        return {
            "source": "user_correction",
            "confidence": 1.0,
            "algorithm_version": run.algorithm_version,
            "reconstruction_run_id": run.id,
            "user_locked": True,
        }

    def lock_record(record: object) -> None:
        values: dict[str, object] = {
            "source": "user_correction",
            "confidence": 1.0,
            "user_locked": True,
            "updated_at": datetime.now(UTC),
        }
        for field, value in values.items():
            if hasattr(record, field):
                setattr(record, field, value)

    def lock_reconstruction_parents(db: DbSession, record: object) -> None:
        if isinstance(record, orm.Moment):
            stop = db.get(orm.Stop, record.stop_id)
            if stop is not None:
                lock_record(stop)
                lock_reconstruction_parents(db, stop)
        elif isinstance(record, orm.Stop):
            day = db.get(orm.TripDay, record.trip_day_id)
            place = db.get(orm.Place, record.place_id)
            if day is not None:
                lock_record(day)
            if place is not None:
                lock_record(place)
        elif isinstance(record, orm.TripLeg):
            day = db.get(orm.TripDay, record.trip_day_id)
            if day is not None:
                lock_record(day)

    def route_line_wkt(db: DbSession, from_stop_id: UUID, to_stop_id: UUID) -> str | None:
        return db.execute(
            text(
                """
                SELECT ST_AsEWKT(ST_MakeLine(source.centroid::geometry, target.centroid::geometry))
                FROM stops source, stops target
                WHERE source.id = CAST(:from_stop_id AS uuid)
                    AND target.id = CAST(:to_stop_id AS uuid)
                """
            ),
            {"from_stop_id": str(from_stop_id), "to_stop_id": str(to_stop_id)},
        ).scalar_one_or_none()

    def replace_stop_leg_endpoint(
        db: DbSession, leg: orm.TripLeg, from_stop: orm.Stop, to_stop: orm.Stop
    ) -> None:
        duplicate = db.execute(
            select(orm.TripLeg).where(
                orm.TripLeg.id != leg.id,
                orm.TripLeg.from_stop_id == from_stop.id,
                orm.TripLeg.to_stop_id == to_stop.id,
                orm.TripLeg.reconstruction_run_id == leg.reconstruction_run_id,
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            lock_record(duplicate)
            db.delete(leg)
            return
        leg.from_stop_id = from_stop.id
        leg.to_stop_id = to_stop.id
        leg.trip_day_id = from_stop.trip_day_id
        leg.geometry = route_line_wkt(db, from_stop.id, to_stop.id)
        lock_record(leg)

    def add_stop_leg_if_missing(
        db: DbSession, run: orm.ReconstructionRun, from_stop: orm.Stop, to_stop: orm.Stop
    ) -> None:
        if from_stop.id == to_stop.id:
            return
        existing = db.execute(
            select(orm.TripLeg).where(
                orm.TripLeg.from_stop_id == from_stop.id,
                orm.TripLeg.to_stop_id == to_stop.id,
                orm.TripLeg.reconstruction_run_id == run.id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            lock_record(existing)
            return
        db.add(
            orm.TripLeg(
                trip_id=from_stop.trip_id,
                trip_day_id=from_stop.trip_day_id,
                from_stop_id=from_stop.id,
                to_stop_id=to_stop.id,
                route_source=RouteSource.PHOTO_INFERRED.value,
                geometry=route_line_wkt(db, from_stop.id, to_stop.id),
                **correction_generated(run),
            )
        )

    def rebuild_inferred_day_legs_for_edit(
        db: DbSession, run: orm.ReconstructionRun, trip_day_id: UUID
    ) -> None:
        db.execute(
            delete(orm.TripLeg).where(
                orm.TripLeg.trip_day_id == trip_day_id,
                orm.TripLeg.route_source == RouteSource.PHOTO_INFERRED.value,
            )
        )
        stops = list(
            db.scalars(
                select(orm.Stop)
                .where(orm.Stop.trip_day_id == trip_day_id)
                .order_by(orm.Stop.position, orm.Stop.starts_at_utc, orm.Stop.id)
            )
        )
        for previous, current in zip(stops, stops[1:], strict=False):
            existing = db.execute(
                select(orm.TripLeg).where(
                    orm.TripLeg.from_stop_id == previous.id,
                    orm.TripLeg.to_stop_id == current.id,
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue
            db.add(
                orm.TripLeg(
                    trip_id=previous.trip_id,
                    trip_day_id=trip_day_id,
                    from_stop_id=previous.id,
                    to_stop_id=current.id,
                    route_source=RouteSource.PHOTO_INFERRED.value,
                    geometry=route_line_wkt(db, previous.id, current.id),
                    **correction_generated(run),
                )
            )

    def stop_centroid_for_moments(db: DbSession, moment_ids: list[UUID]) -> str | None:
        if not moment_ids:
            return None
        return db.execute(
            text(
                """
                SELECT ST_AsEWKT(
                    ST_SetSRID(
                        ST_MakePoint(
                            AVG(ST_X(media_items.effective_location::geometry)),
                            AVG(ST_Y(media_items.effective_location::geometry))
                        ),
                        4326
                    )
                )
                FROM moment_media
                JOIN media_items ON media_items.id = moment_media.media_item_id
                WHERE moment_media.moment_id = ANY(:moment_ids)
                    AND media_items.effective_location IS NOT NULL
                """
            ),
            {"moment_ids": moment_ids},
        ).scalar_one_or_none()

    def stop_centroid_for_media(db: DbSession, media_ids: list[UUID]) -> str | None:
        if not media_ids:
            return None
        return db.execute(
            text(
                """
                SELECT ST_AsEWKT(
                    ST_SetSRID(
                        ST_MakePoint(
                            AVG(ST_X(effective_location::geometry)),
                            AVG(ST_Y(effective_location::geometry))
                        ),
                        4326
                    )
                )
                FROM media_items
                WHERE id = ANY(:media_ids)
                    AND effective_location IS NOT NULL
                """
            ),
            {"media_ids": media_ids},
        ).scalar_one_or_none()

    def rewire_merged_stop_legs(db: DbSession, source: orm.Stop, target: orm.Stop) -> None:
        legs = list(
            db.scalars(
                select(orm.TripLeg).where(
                    orm.TripLeg.trip_id == source.trip_id,
                    or_(
                        orm.TripLeg.from_stop_id == source.id,
                        orm.TripLeg.to_stop_id == source.id,
                    ),
                )
            )
        )
        for leg in legs:
            if leg.from_stop_id == target.id or leg.to_stop_id == target.id:
                continue
            if leg.from_stop_id == source.id:
                to_stop = db.get(orm.Stop, leg.to_stop_id)
                if to_stop is None:
                    db.delete(leg)
                    continue
                replace_stop_leg_endpoint(db, leg, target, to_stop)
                continue
            from_stop = db.get(orm.Stop, leg.from_stop_id)
            if from_stop is None:
                db.delete(leg)
                continue
            replace_stop_leg_endpoint(db, leg, from_stop, target)

    def get_trip_record(
        db: DbSession, model: type[object], record_id: UUID, trip_id: UUID, label: str
    ) -> Any:
        record = db.get(model, record_id)
        if record is None or getattr(record, "trip_id", None) != trip_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} not found")
        return record

    def first_moment_for_stop(
        db: DbSession, stop: orm.Stop, run: orm.ReconstructionRun
    ) -> orm.Moment:
        moment = db.execute(
            select(orm.Moment)
            .where(orm.Moment.stop_id == stop.id)
            .order_by(orm.Moment.position)
            .limit(1)
        ).scalar_one_or_none()
        if moment is not None:
            return moment
        moment = orm.Moment(
            trip_id=stop.trip_id,
            stop_id=stop.id,
            position=1,
            starts_at_utc=stop.starts_at_utc,
            ends_at_utc=stop.ends_at_utc,
            **correction_generated(run),
        )
        db.add(moment)
        db.flush()
        return moment

    def ordered_stop_moments(db: DbSession, stop_id: UUID) -> list[orm.Moment]:
        return list(
            db.scalars(
                select(orm.Moment)
                .where(orm.Moment.stop_id == stop_id)
                .order_by(
                    orm.Moment.starts_at_utc,
                    orm.Moment.ends_at_utc,
                    orm.Moment.position,
                    orm.Moment.id,
                )
            )
        )

    def renumber_stop_moments(db: DbSession, stop_id: UUID) -> None:
        for position, moment in enumerate(ordered_stop_moments(db, stop_id), start=1):
            moment.position = position
            lock_record(moment)

    def renumber_day_stops(db: DbSession, trip_day_id: UUID) -> None:
        stops = list(
            db.scalars(
                select(orm.Stop)
                .where(orm.Stop.trip_day_id == trip_day_id)
                .order_by(orm.Stop.position, orm.Stop.starts_at_utc, orm.Stop.id)
            )
        )
        for position, stop in enumerate(stops, start=1):
            stop.position = position
            lock_record(stop)

    def normalized_title(value: str | None) -> str | None:
        title = " ".join(value.split()) if value is not None else ""
        return title or None

    def split_stop_titles(stop: orm.Stop) -> tuple[str | None, str | None]:
        title = normalized_title(stop.title)
        if title is None:
            return None, None
        return f"{title} 1"[:255], f"{title} 2"[:255]

    def media_capture_time(media: orm.MediaItem) -> datetime:
        return media.effective_captured_at_utc or media.original_captured_at_utc or media.created_at

    def ordered_stop_media(db: DbSession, stop_id: UUID) -> list[orm.MediaItem]:
        return list(
            db.scalars(
                select(orm.MediaItem)
                .join(orm.MomentMedia, orm.MomentMedia.media_item_id == orm.MediaItem.id)
                .join(orm.Moment, orm.Moment.id == orm.MomentMedia.moment_id)
                .where(orm.Moment.stop_id == stop_id)
                .order_by(
                    orm.Moment.starts_at_utc,
                    orm.Moment.position,
                    orm.MomentMedia.position,
                    orm.MediaItem.effective_captured_at_utc,
                    orm.MediaItem.original_captured_at_utc,
                    orm.MediaItem.created_at,
                    orm.MediaItem.id,
                )
            )
        )

    def replace_stop_moments(
        db: DbSession,
        *,
        run: orm.ReconstructionRun,
        stop: orm.Stop,
        media_items: list[orm.MediaItem],
    ) -> list[orm.Moment]:
        existing_moment_ids = [moment.id for moment in ordered_stop_moments(db, stop.id)]
        if existing_moment_ids:
            db.execute(
                delete(orm.MomentParticipant).where(
                    orm.MomentParticipant.moment_id.in_(existing_moment_ids)
                )
            )
            db.execute(
                delete(orm.MomentMedia).where(orm.MomentMedia.moment_id.in_(existing_moment_ids))
            )
            db.execute(delete(orm.Moment).where(orm.Moment.id.in_(existing_moment_ids)))
            db.flush()

        sorted_media = sorted(media_items, key=lambda item: (media_capture_time(item), item.id))
        groups: list[list[orm.MediaItem]] = []
        current: list[orm.MediaItem] = []
        previous: orm.MediaItem | None = None
        for media in sorted_media:
            if previous is not None:
                gap = (
                    media_capture_time(media) - media_capture_time(previous)
                ).total_seconds() / 60
                if gap > MOMENT_GAP_MINUTES:
                    groups.append(current)
                    current = []
            current.append(media)
            previous = media
        if current:
            groups.append(current)

        created: list[orm.Moment] = []
        for position, group in enumerate(groups, start=1):
            moment = orm.Moment(
                trip_id=stop.trip_id,
                stop_id=stop.id,
                position=position,
                starts_at_utc=min(media_capture_time(item) for item in group),
                ends_at_utc=max(media_capture_time(item) for item in group),
                **correction_generated(run),
            )
            db.add(moment)
            db.flush()
            for media_position, media in enumerate(group, start=1):
                db.add(
                    orm.MomentMedia(
                        trip_id=stop.trip_id,
                        moment_id=moment.id,
                        media_item_id=media.id,
                        position=media_position,
                        **correction_generated(run),
                    )
                )
            for participant_id in sorted({media.contributor_member_id for media in group}):
                db.add(
                    orm.MomentParticipant(
                        trip_id=stop.trip_id,
                        moment_id=moment.id,
                        trip_member_id=participant_id,
                        **correction_generated(run),
                    )
                )
            created.append(moment)
        db.flush()
        return created

    def edit_operation_response(operation: orm.EditOperation) -> EditOperationResponse:
        return EditOperationResponse(
            id=operation.id,
            operationType=operation.operation_type,
            status=operation.status,
            targetType=operation.target_type,
            targetId=operation.target_id,
            beforeValues=operation.before_values,
            afterValues=operation.after_values,
            createdAt=operation.created_at,
        )

    def append_edit_operation(
        db: DbSession,
        *,
        trip_id: UUID,
        member: orm.TripMember,
        actor: AuthenticatedActor,
        operation_type: str,
        payload: dict[str, object],
        before_values: dict[str, object],
        after_values: dict[str, object],
        target_type: str | None,
        target_id: UUID | None,
        review_item_id: UUID | None,
        undo_of_operation_id: UUID | None = None,
    ) -> orm.EditOperation:
        operation = orm.EditOperation(
            trip_id=trip_id,
            operation_type=operation_type,
            status=EditOperationStatus.APPLIED.value,
            actor_user_id=actor.user.id if actor.user is not None else None,
            actor_member_id=member.id,
            review_item_id=review_item_id,
            target_type=target_type,
            target_id=target_id,
            payload=payload,
            before_values=before_values,
            after_values=after_values,
            undo_of_operation_id=undo_of_operation_id,
        )
        db.add(operation)
        db.flush()
        return operation

    def apply_edit_operation(
        db: DbSession,
        *,
        trip_id: UUID,
        actor: AuthenticatedActor,
        member: orm.TripMember,
        payload: EditOperationRequest,
    ) -> orm.EditOperation:
        run = latest_run_for_trip(db, trip_id)
        operation_type = payload.operation_type
        data = payload.payload
        organizer = member.role in {TripMemberRole.OWNER.value, TripMemberRole.EDITOR.value}
        contributor_ops = {
            EditOperationType.MOVE_AFTER_MIDNIGHT_MEDIA.value,
            EditOperationType.EXCLUDE_MEDIA_FROM_STORY.value,
            EditOperationType.SET_SIMILARITY_REPRESENTATIVE.value,
        }
        if not organizer and operation_type not in contributor_ops:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")

        review_item: orm.ReviewItem | None = None
        if payload.review_item_id is not None:
            review_item = db.get(orm.ReviewItem, payload.review_item_id)
            if review_item is None or review_item.trip_id != trip_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Review item not found"
                )

        before: dict[str, object]
        after: dict[str, object]
        target_type: str | None = None
        target_id: UUID | None = None

        if operation_type == EditOperationType.MOVE_MEDIA.value:
            media_id = payload_uuid(data, "mediaItemId")
            media = db.get(orm.MediaItem, media_id)
            if media is None or media.trip_id != trip_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
            moment_id = payload_uuid(data, "momentId")
            moment = db.get(orm.Moment, moment_id)
            if moment is None or moment.trip_id != trip_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Moment not found"
                )
            expected_fresh(moment, payload.expected_updated_at)
            existing = db.execute(
                select(orm.MomentMedia).where(orm.MomentMedia.media_item_id == media_id)
            ).scalar_one_or_none()
            before = {
                "mediaItemId": str(media_id),
                "momentId": str(existing.moment_id) if existing is not None else None,
            }
            if existing is None:
                existing = orm.MomentMedia(
                    trip_id=trip_id,
                    moment_id=moment_id,
                    media_item_id=media_id,
                    position=1,
                    **correction_generated(run),
                )
                db.add(existing)
            else:
                existing.moment_id = moment_id
                lock_record(existing)
            lock_record(moment)
            stop = db.get(orm.Stop, moment.stop_id)
            if stop is not None:
                lock_record(stop)
            after = {"mediaItemId": str(media_id), "momentId": str(moment_id)}
            target_type, target_id = "media_item", media_id

        elif operation_type == EditOperationType.MOVE_AFTER_MIDNIGHT_MEDIA.value:
            media_id = payload_uuid(data, "mediaItemId")
            media = db.get(orm.MediaItem, media_id)
            if media is None or media.trip_id != trip_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
            if not organizer and media.contributor_member_id != member.id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
            expected_fresh(media, payload.expected_updated_at)
            direction = payload_str(data, "direction")
            delta = timedelta(days=-1 if direction == "previous" else 1)
            current = media.effective_captured_at_utc or media.original_captured_at_utc
            if current is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="Media has no time"
                )
            before = record_values(media, ["effective_captured_at_utc", "user_locked"])
            media.effective_captured_at_utc = current + delta
            media.user_locked = True
            media.updated_at = datetime.now(UTC)
            after = record_values(media, ["effective_captured_at_utc", "user_locked"])
            target_type, target_id = "media_item", media_id

        elif operation_type == EditOperationType.MERGE_STOPS.value:
            source = db.get(orm.Stop, payload_uuid(data, "sourceStopId"))
            target = db.get(orm.Stop, payload_uuid(data, "targetStopId"))
            if (
                source is None
                or target is None
                or source.trip_id != trip_id
                or target.trip_id != trip_id
            ):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stop not found")
            expected_fresh(source, payload.expected_updated_at)
            before = {"sourceStopId": str(source.id), "targetStopId": str(target.id)}
            merged_title = normalized_title(target.title)
            for moment in ordered_stop_moments(db, source.id):
                moment.stop_id = target.id
                lock_record(moment)
            db.flush()
            renumber_stop_moments(db, target.id)
            target.starts_at_utc = min(target.starts_at_utc, source.starts_at_utc)
            target.ends_at_utc = max(target.ends_at_utc, source.ends_at_utc)
            target.title = merged_title
            target.centroid = (
                stop_centroid_for_moments(
                    db, [moment.id for moment in ordered_stop_moments(db, target.id)]
                )
                or target.centroid
            )
            lock_record(target)
            lock_reconstruction_parents(db, target)
            db.delete(source)
            db.flush()
            renumber_day_stops(db, target.trip_day_id)
            rebuild_inferred_day_legs_for_edit(db, run, target.trip_day_id)
            after = {"mergedIntoStopId": str(target.id)}
            target_type, target_id = "stop", target.id

        elif operation_type == EditOperationType.SPLIT_STOP.value:
            stop = db.get(orm.Stop, payload_uuid(data, "stopId"))
            if stop is None or stop.trip_id != trip_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stop not found")
            expected_fresh(stop, payload.expected_updated_at)
            moments = ordered_stop_moments(db, stop.id)
            media_items = ordered_stop_media(db, stop.id)
            split_after_media_id: UUID | None = None
            split_after_moment_id: UUID | None = None
            if "afterMediaItemId" in data:
                split_after_media_id = payload_uuid(data, "afterMediaItemId")
            elif "afterMomentId" in data:
                split_after_moment_id = payload_uuid(data, "afterMomentId")
                split_after_moment = next(
                    (moment for moment in moments if moment.id == split_after_moment_id), None
                )
                if split_after_moment is not None:
                    moment_media = [
                        media
                        for media in media_items
                        if db.scalar(
                            select(orm.MomentMedia.id).where(
                                orm.MomentMedia.moment_id == split_after_moment.id,
                                orm.MomentMedia.media_item_id == media.id,
                            )
                        )
                        is not None
                    ]
                    if moment_media:
                        split_after_media_id = moment_media[-1].id
            else:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="afterMediaItemId is required",
                )
            media_index = next(
                (i for i, media in enumerate(media_items) if media.id == split_after_media_id), -1
            )
            if media_index < 0 or media_index == len(media_items) - 1:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="Cannot split stop there"
                )
            kept_media = media_items[: media_index + 1]
            moved_media = media_items[media_index + 1 :]
            next_stop = db.execute(
                select(orm.Stop)
                .where(
                    orm.Stop.trip_day_id == stop.trip_day_id,
                    orm.Stop.position > stop.position,
                )
                .order_by(orm.Stop.position)
                .limit(1)
            ).scalar_one_or_none()
            original_stop_values = record_values(
                stop, ["position", "starts_at_utc", "ends_at_utc", "centroid", "user_locked"]
            )
            following_stops = list(
                db.scalars(
                    select(orm.Stop)
                    .where(
                        orm.Stop.trip_day_id == stop.trip_day_id,
                        orm.Stop.position > stop.position,
                    )
                    .order_by(orm.Stop.position.desc())
                )
            )
            for following_stop in following_stops:
                following_stop.position += 1
                lock_record(following_stop)
            moved_centroid = stop_centroid_for_media(db, [media.id for media in moved_media])
            original_title, new_title = split_stop_titles(stop)
            new_stop = orm.Stop(
                trip_id=trip_id,
                trip_day_id=stop.trip_day_id,
                place_id=stop.place_id,
                title=new_title,
                position=stop.position + 1,
                starts_at_utc=min(media_capture_time(media) for media in moved_media),
                ends_at_utc=stop.ends_at_utc,
                centroid=moved_centroid or stop.centroid,
                **correction_generated(run),
            )
            db.add(new_stop)
            db.flush()
            before = {
                "stopId": str(stop.id),
                "splitAfterMomentId": str(split_after_moment_id)
                if split_after_moment_id is not None
                else None,
                "splitAfterMediaItemId": str(split_after_media_id),
                "momentIds": [str(moment.id) for moment in moments],
                "mediaItemIds": [str(media.id) for media in media_items],
                "movedMediaItemIds": [str(media.id) for media in moved_media],
                "nextStopId": str(next_stop.id) if next_stop is not None else None,
                "originalStop": original_stop_values,
            }
            stop.ends_at_utc = max(media_capture_time(media) for media in kept_media)
            stop.title = original_title
            stop.centroid = (
                stop_centroid_for_media(db, [media.id for media in kept_media]) or stop.centroid
            )
            kept_moments = replace_stop_moments(db, run=run, stop=stop, media_items=kept_media)
            moved_moments = replace_stop_moments(
                db, run=run, stop=new_stop, media_items=moved_media
            )
            for moment in kept_moments + moved_moments:
                lock_record(moment)
            lock_record(stop)
            lock_reconstruction_parents(db, stop)
            db.flush()
            renumber_day_stops(db, stop.trip_day_id)
            rebuild_inferred_day_legs_for_edit(db, run, stop.trip_day_id)
            after = {
                "newStopId": str(new_stop.id),
                "movedMomentIds": [str(moment.id) for moment in moved_moments],
                "movedMediaItemIds": [str(media.id) for media in moved_media],
                "newStopPosition": new_stop.position,
            }
            target_type, target_id = "stop", stop.id

        elif operation_type == EditOperationType.MERGE_MOMENTS.value:
            moment_source = db.get(orm.Moment, payload_uuid(data, "sourceMomentId"))
            moment_target = db.get(orm.Moment, payload_uuid(data, "targetMomentId"))
            if (
                moment_source is None
                or moment_target is None
                or moment_source.trip_id != trip_id
                or moment_target.trip_id != trip_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Moment not found"
                )
            expected_fresh(moment_source, payload.expected_updated_at)
            before = {
                "sourceMomentId": str(moment_source.id),
                "targetMomentId": str(moment_target.id),
            }
            for link in db.scalars(
                select(orm.MomentMedia).where(orm.MomentMedia.moment_id == moment_source.id)
            ):
                link.moment_id = moment_target.id
                lock_record(link)
            for participant in db.scalars(
                select(orm.MomentParticipant).where(
                    orm.MomentParticipant.moment_id == moment_source.id
                )
            ):
                duplicate = db.execute(
                    select(orm.MomentParticipant).where(
                        orm.MomentParticipant.moment_id == moment_target.id,
                        orm.MomentParticipant.trip_member_id == participant.trip_member_id,
                    )
                ).scalar_one_or_none()
                if duplicate is None:
                    participant.moment_id = moment_target.id
                    lock_record(participant)
                else:
                    db.delete(participant)
            moment_target.starts_at_utc = min(
                moment_target.starts_at_utc, moment_source.starts_at_utc
            )
            moment_target.ends_at_utc = max(moment_target.ends_at_utc, moment_source.ends_at_utc)
            lock_record(moment_target)
            lock_reconstruction_parents(db, moment_target)
            db.delete(moment_source)
            after = {"mergedIntoMomentId": str(moment_target.id)}
            target_type, target_id = "moment", moment_target.id

        elif operation_type in {
            EditOperationType.RENAME_DAY.value,
            EditOperationType.RENAME_STOP.value,
            EditOperationType.RENAME_MOMENT.value,
        }:
            model_by_type = {
                EditOperationType.RENAME_DAY.value: (orm.TripDay, "day", "dayId"),
                EditOperationType.RENAME_STOP.value: (orm.Stop, "stop", "stopId"),
                EditOperationType.RENAME_MOMENT.value: (orm.Moment, "moment", "momentId"),
            }
            model, label, key = model_by_type[operation_type]
            record = get_trip_record(db, model, payload_uuid(data, key), trip_id, label)
            expected_fresh(record, payload.expected_updated_at)
            before = record_values(record, ["title", "user_locked"])
            title_field = "title"
            setattr(record, title_field, payload_str(data, "title"))
            lock_record(record)
            lock_reconstruction_parents(db, record)
            after = record_values(record, ["title", "user_locked"])
            target_type, target_id = label, record.id

        elif operation_type in {
            EditOperationType.SET_DAY_NOTE.value,
            EditOperationType.SET_STOP_NOTE.value,
        }:
            model_by_type = {
                EditOperationType.SET_DAY_NOTE.value: (orm.TripDay, "day", "dayId"),
                EditOperationType.SET_STOP_NOTE.value: (orm.Stop, "stop", "stopId"),
            }
            model, label, key = model_by_type[operation_type]
            record = get_trip_record(db, model, payload_uuid(data, key), trip_id, label)
            expected_fresh(record, payload.expected_updated_at)
            before = record_values(record, ["note", "user_locked"])
            record.note = payload_optional_note(data)
            lock_record(record)
            lock_reconstruction_parents(db, record)
            after = record_values(record, ["note", "user_locked"])
            target_type, target_id = label, record.id

        elif operation_type == EditOperationType.MOVE_STOP_ON_MAP.value:
            stop = db.get(orm.Stop, payload_uuid(data, "stopId"))
            if stop is None or stop.trip_id != trip_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stop not found")
            expected_fresh(stop, payload.expected_updated_at)
            lat_value = data.get("latitude", 0)
            lon_value = data.get("longitude", 0)
            lat = float(lat_value) if isinstance(lat_value, str | int | float) else 0.0
            lon = float(lon_value) if isinstance(lon_value, str | int | float) else 0.0
            before = record_values(stop, ["centroid", "user_locked"])
            stop.centroid = f"SRID=4326;POINT({lon} {lat})"
            lock_record(stop)
            lock_reconstruction_parents(db, stop)
            after = record_values(stop, ["centroid", "user_locked"])
            target_type, target_id = "stop", stop.id

        elif operation_type == EditOperationType.CHANGE_ROUTE_MODE.value:
            leg = db.get(orm.TripLeg, payload_uuid(data, "tripLegId"))
            if leg is None or leg.trip_id != trip_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
            expected_fresh(leg, payload.expected_updated_at)
            before = record_values(leg, ["route_source", "user_locked"])
            leg.route_source = payload_str(data, "routeSource")
            lock_record(leg)
            lock_reconstruction_parents(db, leg)
            after = record_values(leg, ["route_source", "user_locked"])
            target_type, target_id = "trip_leg", leg.id

        elif operation_type == EditOperationType.EXCLUDE_MEDIA_FROM_STORY.value:
            media = db.get(orm.MediaItem, payload_uuid(data, "mediaItemId"))
            if media is None or media.trip_id != trip_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
            if not organizer and media.contributor_member_id != member.id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
            expected_fresh(media, payload.expected_updated_at)
            before = record_values(media, ["include_in_story", "user_locked"])
            media.include_in_story = False
            media.user_locked = True
            media.updated_at = datetime.now(UTC)
            after = record_values(media, ["include_in_story", "user_locked"])
            target_type, target_id = "media_item", media.id

        elif operation_type == EditOperationType.LOCK_RECORD.value:
            target_type = payload_str(data, "targetType")
            model_by_target: dict[str, type[object]] = {
                "day": orm.TripDay,
                "stop": orm.Stop,
                "moment": orm.Moment,
                "place": orm.Place,
                "trip_leg": orm.TripLeg,
                "review_item": orm.ReviewItem,
            }
            lock_model = model_by_target.get(target_type)
            if lock_model is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid targetType"
                )
            record = get_trip_record(
                db, lock_model, payload_uuid(data, "targetId"), trip_id, target_type
            )
            expected_fresh(record, payload.expected_updated_at)
            before = record_values(record, ["user_locked"])
            lock_record(record)
            lock_reconstruction_parents(db, record)
            after = record_values(record, ["user_locked"])
            target_id = record.id

        elif operation_type == EditOperationType.SET_SIMILARITY_REPRESENTATIVE.value:
            group = db.get(orm.SimilarityGroup, payload_uuid(data, "similarityGroupId"))
            media = db.get(orm.MediaItem, payload_uuid(data, "mediaItemId"))
            if (
                group is None
                or media is None
                or group.trip_id != trip_id
                or media.trip_id != trip_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Similarity group not found"
                )
            group_link = db.execute(
                select(orm.SimilarityGroupMember).where(
                    orm.SimilarityGroupMember.similarity_group_id == group.id,
                    orm.SimilarityGroupMember.media_item_id == media.id,
                )
            ).scalar_one_or_none()
            if group_link is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Media not in group"
                )
            if not organizer and media.contributor_member_id != member.id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
            before = {
                "representativeMediaItemId": str(group.representative_media_item_id)
                if group.representative_media_item_id
                else None
            }
            for group_member in db.scalars(
                select(orm.SimilarityGroupMember).where(
                    orm.SimilarityGroupMember.similarity_group_id == group.id
                )
            ):
                group_member.is_representative = group_member.media_item_id == media.id
                group_member.user_selected = group_member.media_item_id == media.id
            group.representative_media_item_id = media.id
            group.user_locked = True
            group.updated_at = datetime.now(UTC)
            after = {"representativeMediaItemId": str(media.id)}
            target_type, target_id = "similarity_group", group.id

        elif operation_type in {
            EditOperationType.ACCEPT_CLOCK_OFFSET_SUGGESTION.value,
            EditOperationType.REJECT_CLOCK_OFFSET_SUGGESTION.value,
        }:
            if not organizer:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
            suggestion = db.get(
                orm.DeviceClockOffsetSuggestion,
                payload_uuid(data, "suggestionId"),
            )
            if suggestion is None or suggestion.trip_id != trip_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found"
                )
            expected_fresh(suggestion, payload.expected_updated_at)
            before = record_values(
                suggestion,
                [
                    "status",
                    "offset_seconds",
                    "support_count",
                    "dispersion_seconds",
                    "accepted_at",
                    "rejected_at",
                ],
            )
            now = datetime.now(UTC)
            affected_media_ids: list[str] = []
            if operation_type == EditOperationType.ACCEPT_CLOCK_OFFSET_SUGGESTION.value:
                suggestion.status = SuggestionStatus.ACCEPTED.value
                suggestion.accepted_at = now
                suggestion.user_locked = True
                device = db.get(orm.CaptureDevice, suggestion.capture_device_id)
                if device is not None:
                    device.accepted_clock_offset_seconds = suggestion.offset_seconds
                    device.accepted_suggestion_id = suggestion.id
                    device.updated_at = now
                for media in db.scalars(
                    select(orm.MediaItem).where(
                        orm.MediaItem.trip_id == trip_id,
                        orm.MediaItem.capture_device_id == suggestion.capture_device_id,
                        orm.MediaItem.deleted_at.is_(None),
                    )
                ):
                    if media.original_captured_at_utc is None:
                        continue
                    media.effective_captured_at_utc = media.original_captured_at_utc + timedelta(
                        seconds=suggestion.offset_seconds
                    )
                    media.time_source = "automation"
                    media.time_confidence = suggestion.confidence
                    media.updated_at = now
                    affected_media_ids.append(str(media.id))
                idempotency_key = f"reconstruct-trip:{trip_id}:{suggestion.id}"
                existing_job = db.execute(
                    select(orm.ProcessingJob).where(
                        orm.ProcessingJob.idempotency_key == idempotency_key
                    )
                ).scalar_one_or_none()
                if existing_job is None:
                    db.add(
                        orm.ProcessingJob(
                            job_type=ProcessingJobType.RECONSTRUCT_TRIP.value,
                            target_type=ProcessingTargetType.TRIP.value,
                            target_id=trip_id,
                            idempotency_key=idempotency_key,
                        )
                    )
                resolution = "Accepted clock offset suggestion"
            else:
                suggestion.status = SuggestionStatus.REJECTED.value
                suggestion.rejected_at = now
                suggestion.user_locked = True
                resolution = payload_str(data, "resolution")
            suggestion.updated_at = now
            if review_item is None:
                review_item = db.execute(
                    select(orm.ReviewItem).where(
                        orm.ReviewItem.target_type == "device_clock_offset_suggestion",
                        orm.ReviewItem.target_id == suggestion.id,
                        orm.ReviewItem.trip_id == trip_id,
                    )
                ).scalar_one_or_none()
            if review_item is not None:
                review_item.status = ReviewItemStatus.RESOLVED.value
                review_item.resolution = resolution
                review_item.resolved_by = actor.user.id if actor.user is not None else None
                review_item.resolved_at = now
                review_item.user_locked = True
                review_item.updated_at = now
            after = {
                **record_values(
                    suggestion,
                    ["status", "accepted_at", "rejected_at"],
                ),
                "affectedMediaItemIds": affected_media_ids,
            }
            target_type, target_id = "device_clock_offset_suggestion", suggestion.id

        elif operation_type in {
            EditOperationType.RESOLVE_REVIEW_ITEM.value,
            EditOperationType.DISMISS_REVIEW_ITEM.value,
        }:
            item_id = payload.review_item_id or payload_uuid(data, "reviewItemId")
            item = db.get(orm.ReviewItem, item_id)
            if item is None or item.trip_id != trip_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Review item not found"
                )
            expected_fresh(item, payload.expected_updated_at)
            before = record_values(item, ["status", "resolution", "resolved_by", "resolved_at"])
            item.status = (
                "resolved"
                if operation_type == EditOperationType.RESOLVE_REVIEW_ITEM.value
                else "dismissed"
            )
            item.resolution = payload_str(data, "resolution")
            item.resolved_by = actor.user.id if actor.user is not None else None
            item.resolved_at = datetime.now(UTC)
            item.user_locked = True
            item.updated_at = datetime.now(UTC)
            after = record_values(item, ["status", "resolution", "resolved_by", "resolved_at"])
            target_type, target_id = "review_item", item.id
            review_item = item

        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Unsupported edit operation",
            )

        operation = append_edit_operation(
            db,
            trip_id=trip_id,
            member=member,
            actor=actor,
            operation_type=operation_type,
            payload=data,
            before_values=before,
            after_values=after,
            target_type=target_type,
            target_id=target_id,
            review_item_id=review_item.id if review_item is not None else payload.review_item_id,
        )
        invalidate_story_draft_projection(db, trip_id)
        db.commit()
        rebuild_story_projections(db, trip_id)
        db.refresh(operation)
        return operation

    def undo_latest_edit_operation(
        db: DbSession,
        *,
        trip_id: UUID,
        actor: AuthenticatedActor,
        member: orm.TripMember,
    ) -> orm.EditOperation:
        if member.role not in {TripMemberRole.OWNER.value, TripMemberRole.EDITOR.value}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
        safe_types = {
            EditOperationType.MOVE_MEDIA.value,
            EditOperationType.MOVE_AFTER_MIDNIGHT_MEDIA.value,
            EditOperationType.RENAME_DAY.value,
            EditOperationType.RENAME_STOP.value,
            EditOperationType.RENAME_MOMENT.value,
            EditOperationType.SET_DAY_NOTE.value,
            EditOperationType.SET_STOP_NOTE.value,
            EditOperationType.MOVE_STOP_ON_MAP.value,
            EditOperationType.CHANGE_ROUTE_MODE.value,
            EditOperationType.EXCLUDE_MEDIA_FROM_STORY.value,
            EditOperationType.LOCK_RECORD.value,
            EditOperationType.RESOLVE_REVIEW_ITEM.value,
            EditOperationType.DISMISS_REVIEW_ITEM.value,
        }
        operation = db.execute(
            select(orm.EditOperation)
            .where(
                orm.EditOperation.trip_id == trip_id,
                orm.EditOperation.status == EditOperationStatus.APPLIED.value,
                orm.EditOperation.operation_type.in_(safe_types),
                orm.EditOperation.undo_of_operation_id.is_(None),
            )
            .order_by(orm.EditOperation.created_at.desc(), orm.EditOperation.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if operation is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No safe edit to undo")

        before = operation.before_values
        target_type = operation.target_type
        target_id = operation.target_id
        after: dict[str, object] = {}

        if operation.operation_type == EditOperationType.MOVE_MEDIA.value:
            media_id = UUID(str(before["mediaItemId"]))
            moment_id_value = before.get("momentId")
            link = db.execute(
                select(orm.MomentMedia).where(orm.MomentMedia.media_item_id == media_id)
            ).scalar_one_or_none()
            if link is not None and isinstance(moment_id_value, str):
                link.moment_id = UUID(moment_id_value)
                lock_record(link)
                after = {"mediaItemId": str(media_id), "momentId": moment_id_value}
            else:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot undo edit")
        else:
            model_by_target: dict[str, type[object]] = {
                "media_item": orm.MediaItem,
                "day": orm.TripDay,
                "stop": orm.Stop,
                "moment": orm.Moment,
                "trip_leg": orm.TripLeg,
                "review_item": orm.ReviewItem,
                "place": orm.Place,
            }
            if target_type is None or target_id is None or target_type not in model_by_target:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot undo edit")
            record = get_trip_record(
                db, model_by_target[target_type], target_id, trip_id, target_type
            )
            field_map = {
                "effective_captured_at_utc": "effective_captured_at_utc",
                "include_in_story": "include_in_story",
                "title": "title",
                "note": "note",
                "centroid": "centroid",
                "route_source": "route_source",
                "user_locked": "user_locked",
                "status": "status",
                "resolution": "resolution",
                "resolved_by": "resolved_by",
                "resolved_at": "resolved_at",
            }
            for source_field, record_field in field_map.items():
                if source_field not in before:
                    continue
                value = before[source_field]
                if record_field in {"effective_captured_at_utc", "resolved_at"} and isinstance(
                    value, str
                ):
                    value = datetime.fromisoformat(value)
                if record_field == "resolved_by" and isinstance(value, str):
                    value = UUID(value)
                setattr(record, record_field, value)
            lock_record(record)
            after = record_values(record, [field for field in field_map if hasattr(record, field)])

        operation.status = EditOperationStatus.UNDONE.value
        undo = append_edit_operation(
            db,
            trip_id=trip_id,
            member=member,
            actor=actor,
            operation_type=operation.operation_type,
            payload={"undo": True, "operationId": str(operation.id)},
            before_values=operation.after_values,
            after_values=after,
            target_type=operation.target_type,
            target_id=operation.target_id,
            review_item_id=operation.review_item_id,
            undo_of_operation_id=operation.id,
        )
        invalidate_story_draft_projection(db, trip_id)
        db.commit()
        rebuild_story_projections(db, trip_id)
        db.refresh(undo)
        return undo

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
            transport = (
                UploadTransport.SINGLE_PUT
                if app.state.blob_store.capabilities.supports_single_put_upload
                else UploadTransport.API_PROXY
            )
            grant = upload_grant_response(
                app.state.blob_store.create_upload_grant(
                    UploadGrantRequest(
                        blob_ref=blob_ref,
                        max_size_bytes=upload_file.declared_byte_size
                        or resolved_settings.upload_max_file_bytes,
                        content_type=upload_file.declared_mime_type,
                        transport=transport,
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

    def upload_session_for_actor(
        db: DbSession,
        upload_session_id: UUID,
        actor: AuthenticatedActor,
    ) -> tuple[orm.UploadSession, orm.TripMember]:
        upload_session = db.get(orm.UploadSession, upload_session_id)
        if upload_session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Upload session not found"
            )
        member = member_for_actor(db, upload_session.trip_id, actor)
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
        actor: AuthenticatedActor = Depends(current_actor),
        db: DbSession = Depends(db_session),
    ) -> UploadSessionResponse:
        require_csrf(request)
        member = require_member_for_actor(db, trip_id, actor)
        rate_limit_action(
            request,
            "upload_registration_rate_limiter",
            "create-upload-session",
            f"{trip_id}:{member.id}",
        )
        if member.role == TripMemberRole.VIEWER.value:
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
        actor: AuthenticatedActor = Depends(current_actor),
        db: DbSession = Depends(db_session),
    ) -> UploadSessionsListResponse:
        member = require_member_for_actor(db, trip_id, actor)
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
        actor: AuthenticatedActor = Depends(current_actor),
        db: DbSession = Depends(db_session),
    ) -> UploadSessionResponse:
        upload_session, _ = upload_session_for_actor(db, upload_session_id, actor)
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
        actor: AuthenticatedActor = Depends(current_actor),
        db: DbSession = Depends(db_session),
    ) -> CompleteUploadFileResponse:
        require_csrf(request)
        upload_file = db.get(orm.UploadFile, upload_file_id)
        if upload_file is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")
        upload_session, member = upload_session_for_actor(db, upload_file.upload_session_id, actor)
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
            original_retention_state=OriginalRetentionState.TEMPORARY.value,
            sha256=metadata.checksum,
            visibility=MediaVisibility.STORY.value,
            include_in_story=True,
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
        actor: AuthenticatedActor = Depends(current_actor),
        db: DbSession = Depends(db_session),
    ) -> Response:
        require_csrf(request)
        upload_file = db.get(orm.UploadFile, upload_file_id)
        if upload_file is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")
        upload_session_for_actor(db, upload_file.upload_session_id, actor)
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

    @app.get("/trips/{trip_id}/media", response_model=MediaListResponse)
    def list_media(
        trip_id: UUID,
        actor: AuthenticatedActor = Depends(current_actor),
        db: DbSession = Depends(db_session),
    ) -> MediaListResponse:
        member = require_member_for_actor(db, trip_id, actor)
        statement = (
            select(orm.MediaItem, orm.TripMember)
            .join(orm.TripMember, orm.TripMember.id == orm.MediaItem.contributor_member_id)
            .where(orm.MediaItem.trip_id == trip_id, orm.MediaItem.deleted_at.is_(None))
            .order_by(orm.MediaItem.created_at.desc(), orm.MediaItem.id)
        )
        if actor.is_guest:
            statement = statement.where(orm.MediaItem.contributor_member_id == member.id)
        rows = db.execute(statement).all()
        group_summary = similarity_summary_by_media(db, trip_id)
        return MediaListResponse(
            media=[
                media_item_response(
                    db,
                    media_item,
                    contributor,
                    group_summary.get(media_item.id),
                    can_update_visibility=actor_can_update_media_visibility(
                        media_item, contributor, member, actor
                    ),
                )
                for media_item, contributor in rows
            ]
        )

    @app.get("/trips/{trip_id}/similarity-groups", response_model=SimilarityGroupsResponse)
    def list_similarity_groups(
        trip_id: UUID,
        actor: AuthenticatedActor = Depends(current_actor),
        db: DbSession = Depends(db_session),
    ) -> SimilarityGroupsResponse:
        member = require_member_for_actor(db, trip_id, actor)
        statement = (
            select(orm.SimilarityGroup, orm.SimilarityGroupMember, orm.MediaItem, orm.TripMember)
            .join(
                orm.SimilarityGroupMember,
                orm.SimilarityGroupMember.similarity_group_id == orm.SimilarityGroup.id,
            )
            .join(orm.MediaItem, orm.MediaItem.id == orm.SimilarityGroupMember.media_item_id)
            .join(orm.TripMember, orm.TripMember.id == orm.MediaItem.contributor_member_id)
            .where(
                orm.SimilarityGroup.trip_id == trip_id,
                orm.MediaItem.deleted_at.is_(None),
            )
            .order_by(orm.SimilarityGroup.created_at, orm.SimilarityGroupMember.rank)
        )
        if actor.is_guest:
            statement = statement.where(orm.MediaItem.contributor_member_id == member.id)
        rows = db.execute(statement).all()
        by_group: dict[UUID, tuple[orm.SimilarityGroup, list[SimilarityMemberResponse]]] = {}
        for group, group_member, media_item, contributor in rows:
            by_group.setdefault(group.id, (group, []))[1].append(
                SimilarityMemberResponse(
                    mediaItemId=media_item.id,
                    filename=media_item.original_filename,
                    contributor=contributor.display_name,
                    isRepresentative=group_member.is_representative,
                    technicalScore=group_member.technical_score,
                    similarityScore=group_member.similarity_score,
                    signals=group_member.signals,
                )
            )
        return SimilarityGroupsResponse(
            groups=[
                SimilarityGroupResponse(
                    id=group.id,
                    groupType=group.group_type,
                    representativeMediaItemId=group.representative_media_item_id,
                    memberCount=group.member_count,
                    reason=group.reason,
                    confidence=group.confidence,
                    members=members,
                )
                for group, members in by_group.values()
            ]
        )

    @app.post("/media/{media_item_id}/retry", response_model=MediaItemResponse)
    def retry_media_processing(
        media_item_id: UUID,
        request: Request,
        actor: AuthenticatedActor = Depends(current_actor),
        db: DbSession = Depends(db_session),
    ) -> MediaItemResponse:
        require_csrf(request)
        media_item = db.get(orm.MediaItem, media_item_id)
        if media_item is None or media_item.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
        member = member_for_actor(db, media_item.trip_id, actor)
        if member is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
        if member.role not in {TripMemberRole.OWNER.value, TripMemberRole.EDITOR.value} and (
            media_item.contributor_member_id != member.id
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
        if media_item.original_retention_state == OriginalRetentionState.DELETED.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Original file is no longer retained",
            )

        job = db.execute(
            select(orm.ProcessingJob).where(
                orm.ProcessingJob.idempotency_key == f"ingest-media:{media_item.id}"
            )
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        if job is None:
            job = orm.ProcessingJob(
                job_type=ProcessingJobType.INGEST_MEDIA.value,
                target_type=ProcessingTargetType.MEDIA_ITEM.value,
                target_id=media_item.id,
                idempotency_key=f"ingest-media:{media_item.id}",
            )
            db.add(job)
        job.state = ProcessingJobState.PENDING.value
        job.attempts = 0
        job.run_after = now
        job.locked_at = None
        job.locked_by = None
        job.error_code = None
        job.error_message = None
        job.started_at = None
        job.finished_at = None
        media_item.processing_state = ProcessingState.PENDING.value
        media_item.updated_at = now
        db.commit()
        contributor = db.get(orm.TripMember, media_item.contributor_member_id)
        if contributor is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
        return media_item_response(
            db,
            media_item,
            contributor,
            can_update_visibility=media_item.contributor_member_id == member.id,
        )

    @app.patch("/media/{media_item_id}", response_model=MediaItemResponse)
    def update_media(
        media_item_id: UUID,
        payload: MediaUpdateRequest,
        request: Request,
        actor: AuthenticatedActor = Depends(current_actor),
        db: DbSession = Depends(db_session),
    ) -> MediaItemResponse:
        require_csrf(request)
        media_item = db.get(orm.MediaItem, media_item_id)
        if media_item is None or media_item.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
        member = member_for_actor(db, media_item.trip_id, actor)
        if member is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
        contributor = db.get(orm.TripMember, media_item.contributor_member_id)
        if contributor is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")

        is_owner_editor = member.role in {TripMemberRole.OWNER.value, TripMemberRole.EDITOR.value}
        is_contributor_owner = actor_can_update_media_visibility(
            media_item, contributor, member, actor
        )
        if not is_owner_editor and not is_contributor_owner:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")

        if is_contributor_owner and not is_owner_editor:
            if payload.visibility is not None:
                media_item.visibility = payload.visibility
                media_item.user_locked = True
            if payload.include_in_story is not None:
                media_item.include_in_story = payload.include_in_story
            if payload.deleted:
                media_item.deleted_at = datetime.now(UTC)
                media_item.include_in_story = False
        else:
            if payload.visibility is not None:
                if media_item.contributor_member_id != member.id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Cannot change contributor visibility",
                    )
                media_item.visibility = payload.visibility
                media_item.user_locked = True
            if payload.include_in_story is not None:
                if (
                    media_item.visibility == MediaVisibility.PRIVATE.value
                    and payload.include_in_story
                ):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Contributor restricted this media",
                    )
                media_item.include_in_story = payload.include_in_story

        media_item.updated_at = datetime.now(UTC)
        invalidate_story_draft_projection(db, media_item.trip_id)
        db.commit()
        rebuild_story_projections(db, media_item.trip_id)
        return media_item_response(
            db,
            media_item,
            contributor,
            can_update_visibility=is_contributor_owner,
        )

    def story_update_status(
        db: DbSession,
        trip_id: UUID,
        latest_run: orm.ReconstructionRun | None,
    ) -> StoryUpdateStatusResponse:
        ready_filters = (
            orm.MediaItem.trip_id == trip_id,
            orm.MediaItem.deleted_at.is_(None),
            orm.MediaItem.processing_state == ProcessingState.READY.value,
        )
        ready_media_count = (
            db.scalar(select(func.count()).select_from(orm.MediaItem).where(*ready_filters)) or 0
        )
        if latest_run is None:
            return StoryUpdateStatusResponse(
                needsUpdate=ready_media_count > 0,
                unassignedReadyMediaCount=ready_media_count,
                readyMediaCount=ready_media_count,
                storyMediaCount=0,
            )

        represented_media_ids = select(orm.MomentMedia.media_item_id).where(
            orm.MomentMedia.trip_id == trip_id,
            or_(
                orm.MomentMedia.reconstruction_run_id == latest_run.id,
                orm.MomentMedia.user_locked.is_(True),
            ),
        )
        open_review_media_ids = select(orm.ReviewItem.media_item_id).where(
            orm.ReviewItem.trip_id == trip_id,
            orm.ReviewItem.media_item_id.is_not(None),
            orm.ReviewItem.status == ReviewItemStatus.OPEN.value,
        )
        story_media_count = (
            db.scalar(
                select(func.count(func.distinct(orm.MomentMedia.media_item_id)))
                .select_from(orm.MomentMedia)
                .join(orm.MediaItem, orm.MediaItem.id == orm.MomentMedia.media_item_id)
                .where(
                    orm.MomentMedia.trip_id == trip_id,
                    or_(
                        orm.MomentMedia.reconstruction_run_id == latest_run.id,
                        orm.MomentMedia.user_locked.is_(True),
                    ),
                    orm.MediaItem.deleted_at.is_(None),
                    orm.MediaItem.processing_state == ProcessingState.READY.value,
                )
            )
            or 0
        )
        unassigned_ready_media_count = (
            db.scalar(
                select(func.count())
                .select_from(orm.MediaItem)
                .where(
                    *ready_filters,
                    orm.MediaItem.id.notin_(represented_media_ids),
                    orm.MediaItem.id.notin_(open_review_media_ids),
                )
            )
            or 0
        )
        return StoryUpdateStatusResponse(
            needsUpdate=unassigned_ready_media_count > 0,
            unassignedReadyMediaCount=unassigned_ready_media_count,
            readyMediaCount=ready_media_count,
            storyMediaCount=story_media_count,
        )

    def display_positions_for_stops(
        *,
        stops: list[orm.Stop],
        raw_legs_by_day: dict[UUID, list[tuple[orm.TripLeg, dict[str, object] | None]]],
    ) -> dict[UUID, str]:
        display_positions: dict[UUID, str] = {}
        stops_by_day: dict[UUID, list[orm.Stop]] = defaultdict(list)
        for stop in stops:
            stops_by_day[stop.trip_day_id].append(stop)

        for trip_day_id, day_stops in stops_by_day.items():
            ordered_stops = sorted(
                day_stops,
                key=lambda stop: (stop.starts_at_utc, stop.ends_at_utc, stop.position, stop.id),
            )
            stop_ids = {stop.id for stop in ordered_stops}
            if not raw_legs_by_day.get(trip_day_id):
                for index, stop in enumerate(ordered_stops, start=1):
                    display_positions[stop.id] = str(index)
                continue
            parent_ids: dict[UUID, set[UUID]] = {stop.id: set() for stop in ordered_stops}
            for leg, _ in raw_legs_by_day.get(trip_day_id, []):
                if leg.from_stop_id in stop_ids and leg.to_stop_id in stop_ids:
                    parent_ids[leg.to_stop_id].add(leg.from_stop_id)

            rank_by_stop_id: dict[UUID, int] = {}
            remaining = set(stop_ids)
            while remaining:
                progressed = False
                for stop in ordered_stops:
                    if stop.id not in remaining:
                        continue
                    parents = parent_ids[stop.id]
                    if not parents:
                        rank_by_stop_id[stop.id] = 1
                    elif parents.issubset(rank_by_stop_id):
                        rank_by_stop_id[stop.id] = (
                            max(rank_by_stop_id[parent_id] for parent_id in parents) + 1
                        )
                    else:
                        continue
                    remaining.remove(stop.id)
                    progressed = True
                if not progressed:
                    for stop in ordered_stops:
                        if stop.id in remaining:
                            rank_by_stop_id[stop.id] = stop.position
                    break

            stops_by_rank: dict[int, list[orm.Stop]] = defaultdict(list)
            for stop in ordered_stops:
                stops_by_rank[rank_by_stop_id.get(stop.id, stop.position)].append(stop)

            for rank, rank_stops in stops_by_rank.items():
                sorted_rank_stops = sorted(
                    rank_stops,
                    key=lambda stop: (stop.starts_at_utc, stop.ends_at_utc, stop.position, stop.id),
                )
                if len(sorted_rank_stops) == 1:
                    display_positions[sorted_rank_stops[0].id] = str(rank)
                    continue
                for index, stop in enumerate(sorted_rank_stops):
                    display_positions[stop.id] = f"{rank}{alpha_suffix(index)}"

        return display_positions

    def alpha_suffix(index: int) -> str:
        value = index
        result = ""
        while True:
            result = chr(ord("a") + (value % 26)) + result
            value = value // 26 - 1
            if value < 0:
                return result

    def display_position_sort_key(value: str | None) -> tuple[int, str]:
        if not value:
            return (0, "")
        digits = ""
        suffix = ""
        for character in value:
            if character.isdigit() and not suffix:
                digits += character
            else:
                suffix += character
        return (int(digits) if digits else 0, suffix)

    def reconstruction_response(db: DbSession, trip_id: UUID) -> ReconstructionResponse:
        latest_run = db.execute(
            select(orm.ReconstructionRun)
            .where(orm.ReconstructionRun.trip_id == trip_id)
            .order_by(orm.ReconstructionRun.created_at.desc(), orm.ReconstructionRun.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        story_update = story_update_status(db, trip_id, latest_run)
        if latest_run is None:
            return ReconstructionResponse(
                latestRun=None,
                days=[],
                reviewItems=[],
                storyUpdate=story_update,
            )

        stop_lat: Any = literal_column("ST_Y(stops.centroid::geometry)").label("latitude")
        stop_lon: Any = literal_column("ST_X(stops.centroid::geometry)").label("longitude")
        days = list(
            db.execute(
                select(orm.TripDay)
                .where(
                    orm.TripDay.trip_id == trip_id,
                    or_(
                        orm.TripDay.reconstruction_run_id == latest_run.id,
                        orm.TripDay.user_locked.is_(True),
                    ),
                )
                .order_by(
                    orm.TripDay.day_date,
                    orm.TripDay.starts_at_utc,
                    orm.TripDay.position,
                    orm.TripDay.id,
                )
            ).scalars()
        )
        stops = list(
            db.execute(
                select(orm.Stop, orm.Place, stop_lat, stop_lon)
                .join(orm.Place, orm.Place.id == orm.Stop.place_id)
                .where(
                    orm.Stop.trip_id == trip_id,
                    or_(
                        orm.Stop.reconstruction_run_id == latest_run.id,
                        orm.Stop.user_locked.is_(True),
                    ),
                )
                .order_by(orm.Stop.position)
            ).all()
        )
        stop_position_by_id = {stop.id: stop.position for stop, _, _, _ in stops}
        moments = list(
            db.execute(
                select(orm.Moment)
                .where(
                    orm.Moment.trip_id == trip_id,
                    or_(
                        orm.Moment.reconstruction_run_id == latest_run.id,
                        orm.Moment.user_locked.is_(True),
                    ),
                )
                .order_by(
                    orm.Moment.stop_id,
                    orm.Moment.starts_at_utc,
                    orm.Moment.ends_at_utc,
                    orm.Moment.position,
                    orm.Moment.id,
                )
            ).scalars()
        )
        media_lat: Any = literal_column("ST_Y(media_items.effective_location::geometry)").label(
            "latitude"
        )
        media_lon: Any = literal_column("ST_X(media_items.effective_location::geometry)").label(
            "longitude"
        )
        moment_media_rows = db.execute(
            select(
                orm.MomentMedia.moment_id,
                orm.Moment.stop_id,
                orm.MediaItem,
                orm.TripMember,
                media_lat,
                media_lon,
            )
            .join(orm.Moment, orm.Moment.id == orm.MomentMedia.moment_id)
            .join(orm.MediaItem, orm.MediaItem.id == orm.MomentMedia.media_item_id)
            .join(orm.TripMember, orm.TripMember.id == orm.MediaItem.contributor_member_id)
            .where(
                orm.MomentMedia.trip_id == trip_id,
                or_(
                    orm.MomentMedia.reconstruction_run_id == latest_run.id,
                    orm.MomentMedia.user_locked.is_(True),
                ),
            )
            .order_by(orm.MediaItem.effective_captured_at_utc, orm.MediaItem.created_at)
        ).all()
        contributors_by_moment: dict[UUID, set[UUID]] = {}
        contributors_by_stop: dict[UUID, set[UUID]] = {}
        media_by_moment: dict[UUID, list[ReconstructionMediaResponse]] = {}
        local_times_by_moment: dict[UUID, list[datetime]] = {}
        local_times_by_stop: dict[UUID, list[datetime]] = {}
        for moment_id, stop_id, media_item, contributor, latitude, longitude in moment_media_rows:
            contributor_id = media_item.contributor_member_id
            contributors_by_moment.setdefault(moment_id, set()).add(contributor_id)
            contributors_by_stop.setdefault(stop_id, set()).add(contributor_id)
            local_capture = media_local_capture(media_item)
            if local_capture is not None:
                local_times_by_moment.setdefault(moment_id, []).append(local_capture)
                local_times_by_stop.setdefault(stop_id, []).append(local_capture)
            thumbnail = next(
                (asset for asset in media_item.assets if asset.asset_type == "thumbnail"),
                None,
            )
            preview = next(
                (asset for asset in media_item.assets if asset.asset_type == "display"),
                None,
            )
            captured_at = (
                media_item.effective_captured_at_utc
                or media_item.original_captured_at_utc
                or media_item.original_captured_at_local
            )
            media_by_moment.setdefault(moment_id, []).append(
                ReconstructionMediaResponse(
                    id=media_item.id,
                    filename=media_item.original_filename,
                    capturedAt=captured_at,
                    capturedAtLocal=local_capture,
                    latitude=float(latitude) if latitude is not None else None,
                    longitude=float(longitude) if longitude is not None else None,
                    contributorMemberId=contributor.id,
                    contributor=contributor.display_name,
                    thumbnailUrl=(
                        media_asset_response(thumbnail).download_url
                        if thumbnail is not None
                        else None
                    ),
                    previewUrl=(
                        media_asset_response(preview).download_url if preview is not None else None
                    ),
                )
            )

        leg_geometry: Any = literal_column("ST_AsGeoJSON(trip_legs.geometry::geometry)").label(
            "geometry"
        )
        leg_rows = db.execute(
            select(orm.TripLeg, leg_geometry)
            .where(
                orm.TripLeg.trip_id == trip_id,
                or_(
                    orm.TripLeg.reconstruction_run_id == latest_run.id,
                    orm.TripLeg.user_locked.is_(True),
                ),
            )
            .order_by(orm.TripLeg.created_at, orm.TripLeg.id)
        ).all()
        raw_legs_by_day: dict[UUID, list[tuple[orm.TripLeg, dict[str, object] | None]]] = {}
        for leg, geometry_json in leg_rows:
            geometry = json.loads(geometry_json) if isinstance(geometry_json, str) else None
            raw_legs_by_day.setdefault(leg.trip_day_id, []).append((leg, geometry))

        stop_display_position_by_id = display_positions_for_stops(
            stops=[stop for stop, _, _, _ in stops],
            raw_legs_by_day=raw_legs_by_day,
        )
        legs_by_day: dict[UUID, list[ReconstructionLegResponse]] = {}
        for trip_day_id, raw_legs in raw_legs_by_day.items():
            outgoing_counts: dict[UUID, int] = defaultdict(int)
            incoming_counts: dict[UUID, int] = defaultdict(int)
            for leg, _ in raw_legs:
                outgoing_counts[leg.from_stop_id] += 1
                incoming_counts[leg.to_stop_id] += 1
            for leg, geometry in raw_legs:
                is_forked = (
                    outgoing_counts[leg.from_stop_id] > 1 or incoming_counts[leg.to_stop_id] > 1
                )
                legs_by_day.setdefault(trip_day_id, []).append(
                    ReconstructionLegResponse(
                        id=leg.id,
                        fromStopId=leg.from_stop_id,
                        toStopId=leg.to_stop_id,
                        routeSource=leg.route_source,
                        isForked=is_forked,
                        geometry=geometry,
                    )
                )
        for day_legs in legs_by_day.values():
            day_legs.sort(
                key=lambda leg: (
                    stop_position_by_id.get(leg.from_stop_id, 0),
                    stop_position_by_id.get(leg.to_stop_id, 0),
                    str(leg.id),
                )
            )

        moments_by_stop: dict[UUID, list[ReconstructionMomentResponse]] = {}
        for moment in moments:
            contributors = contributors_by_moment.get(moment.id, set())
            moment_local_times = local_times_by_moment.get(moment.id, [])
            moment_media = media_by_moment.get(moment.id, [])
            moments_by_stop.setdefault(moment.stop_id, []).append(
                ReconstructionMomentResponse(
                    id=moment.id,
                    position=moment.position,
                    title=moment.title,
                    startsAt=moment.starts_at_utc,
                    endsAt=moment.ends_at_utc,
                    startsAtLocal=min(moment_local_times) if moment_local_times else None,
                    endsAtLocal=max(moment_local_times) if moment_local_times else None,
                    mediaCount=len(moment_media),
                    contributorCount=len(contributors),
                    media=moment_media,
                )
            )

        stops_by_day: dict[UUID, list[ReconstructionStopResponse]] = {}
        for stop, place, latitude, longitude in stops:
            moment_items = moments_by_stop.get(stop.id, [])
            stop_local_times = local_times_by_stop.get(stop.id, [])
            media_count = sum(item.media_count for item in moment_items)
            contributor_count = len(contributors_by_stop.get(stop.id, set()))
            stops_by_day.setdefault(stop.trip_day_id, []).append(
                ReconstructionStopResponse(
                    id=stop.id,
                    position=stop.position,
                    displayPosition=stop_display_position_by_id.get(stop.id),
                    title=stop.title,
                    note=stop.note,
                    startsAt=stop.starts_at_utc,
                    endsAt=stop.ends_at_utc,
                    startsAtLocal=min(stop_local_times) if stop_local_times else None,
                    endsAtLocal=max(stop_local_times) if stop_local_times else None,
                    placeName=place.name,
                    latitude=float(latitude) if latitude is not None else None,
                    longitude=float(longitude) if longitude is not None else None,
                    mediaCount=media_count,
                    contributorCount=contributor_count,
                    moments=moment_items,
                )
            )
        for day_stops in stops_by_day.values():
            day_stops.sort(
                key=lambda stop: (
                    display_position_sort_key(stop.display_position),
                    stop.starts_at,
                    stop.ends_at,
                    stop.position,
                    stop.id,
                )
            )

        review_items = list(
            db.execute(
                select(orm.ReviewItem)
                .where(
                    orm.ReviewItem.trip_id == trip_id,
                    or_(
                        orm.ReviewItem.reconstruction_run_id == latest_run.id,
                        orm.ReviewItem.user_locked.is_(True),
                    ),
                )
                .order_by(orm.ReviewItem.created_at, orm.ReviewItem.id)
            ).scalars()
        )
        return ReconstructionResponse(
            latestRun=ReconstructionRunResponse(
                id=latest_run.id,
                state=latest_run.state,
                algorithmVersion=latest_run.algorithm_version,
                summary=latest_run.summary,
                startedAt=latest_run.started_at,
                finishedAt=latest_run.finished_at,
            ),
            days=[
                ReconstructionDayResponse(
                    id=day.id,
                    date=day.day_date,
                    position=position,
                    title=day.title,
                    note=day.note,
                    stops=stops_by_day.get(day.id, []),
                    legs=legs_by_day.get(day.id, []),
                )
                for position, day in enumerate(days, start=1)
            ],
            reviewItems=[
                ReviewItemResponse(
                    id=item.id,
                    itemType=item.item_type,
                    severity=item.severity,
                    confidence=item.confidence,
                    targetType=item.target_type,
                    targetId=item.target_id,
                    targetRefs=item.target_refs,
                    payload=item.payload,
                    status=item.status,
                    message=item.message,
                    mediaItemId=item.media_item_id,
                    resolution=item.resolution,
                    resolvedBy=item.resolved_by,
                    resolvedAt=item.resolved_at,
                )
                for item in review_items
            ],
            storyUpdate=story_update,
        )

    STORY_PHOTO_PROJECTION_SCHEMA_VERSION = 1
    DOWNLOAD_GRANT_REFRESH_WINDOW = timedelta(seconds=60)

    def invalidate_story_draft_projection(db: DbSession, trip_id: UUID) -> None:
        db.execute(
            delete(orm.StoryDraftProjection).where(orm.StoryDraftProjection.trip_id == trip_id)
        )
        db.execute(
            delete(orm.StoryDayPhotoProjection).where(
                orm.StoryDayPhotoProjection.trip_id == trip_id
            )
        )
        db.execute(
            delete(orm.StoryStopPhotoProjection).where(
                orm.StoryStopPhotoProjection.trip_id == trip_id
            )
        )

    def asset_ids_for_reconstruction(
        db: DbSession, response: ReconstructionResponse
    ) -> dict[UUID, dict[str, UUID]]:
        media_ids: list[UUID] = [
            media.id
            for day in response.days
            for stop in day.stops
            for moment in stop.moments
            for media in moment.media
        ]
        if not media_ids:
            return {}
        rows = db.execute(
            select(
                orm.MediaAsset.media_item_id,
                orm.MediaAsset.asset_type,
                orm.MediaAsset.id,
            ).where(
                orm.MediaAsset.media_item_id.in_(media_ids),
                orm.MediaAsset.asset_type.in_(
                    [MediaAssetType.THUMBNAIL.value, MediaAssetType.DISPLAY.value]
                ),
            )
        ).all()
        assets: dict[UUID, dict[str, UUID]] = {}
        for media_item_id, asset_type, asset_id in rows:
            assets.setdefault(media_item_id, {})[asset_type] = asset_id
        return assets

    def story_draft_projection_payload(
        db: DbSession, response: ReconstructionResponse
    ) -> dict[str, object]:
        payload = response.model_dump(mode="json", by_alias=True)
        payload["reviewItems"] = []
        asset_ids_by_media = asset_ids_for_reconstruction(db, response)
        for day in payload.get("days", []):
            if not isinstance(day, dict):
                continue
            for stop in day.get("stops", []):
                if not isinstance(stop, dict):
                    continue
                for moment in stop.get("moments", []):
                    if not isinstance(moment, dict):
                        continue
                    for media in moment.get("media", []):
                        if not isinstance(media, dict):
                            continue
                        media_id = media.get("id")
                        try:
                            media_uuid = UUID(str(media_id))
                        except (TypeError, ValueError):
                            continue
                        asset_ids = asset_ids_by_media.get(media_uuid, {})
                        thumbnail_id = asset_ids.get(MediaAssetType.THUMBNAIL.value)
                        preview_id = asset_ids.get(MediaAssetType.DISPLAY.value)
                        media["thumbnailUrl"] = None
                        media["previewUrl"] = None
                        if thumbnail_id is not None:
                            media["thumbnailAssetId"] = str(thumbnail_id)
                        if preview_id is not None:
                            media["previewAssetId"] = str(preview_id)
        return payload

    def hydrate_story_draft_projection(
        db: DbSession, payload: dict[str, object]
    ) -> ReconstructionResponse:
        hydrated = json.loads(json.dumps(payload))
        representative_asset_ids: set[UUID] = set()
        media_by_asset_id: dict[UUID, dict[str, object]] = {}
        for day in hydrated.get("days", []):
            if not isinstance(day, dict):
                continue
            for stop in day.get("stops", []):
                if not isinstance(stop, dict):
                    continue
                first_stop_thumbnail_id: UUID | None = None
                for moment in stop.get("moments", []):
                    if not isinstance(moment, dict):
                        continue
                    for media in moment.get("media", []):
                        if not isinstance(media, dict):
                            continue
                        asset_id = media.get("thumbnailAssetId")
                        if asset_id is None:
                            continue
                        try:
                            asset_uuid = UUID(str(asset_id))
                        except ValueError:
                            continue
                        media_by_asset_id[asset_uuid] = media
                        first_stop_thumbnail_id = first_stop_thumbnail_id or asset_uuid
                if first_stop_thumbnail_id is not None:
                    representative_asset_ids.add(first_stop_thumbnail_id)
        if representative_asset_ids:
            assets = db.execute(
                select(orm.MediaAsset).where(orm.MediaAsset.id.in_(representative_asset_ids))
            ).scalars()
            for asset in assets:
                media = media_by_asset_id.get(asset.id)
                if media is not None:
                    media["thumbnailUrl"] = media_asset_response(asset).download_url
        return ReconstructionResponse.model_validate(hydrated)

    def save_story_draft_projection(
        db: DbSession,
        *,
        trip_id: UUID,
        source_reconstruction_run_id: UUID,
        payload: dict[str, object],
    ) -> None:
        now = datetime.now(UTC)
        db.execute(
            delete(orm.StoryDraftProjection).where(orm.StoryDraftProjection.trip_id == trip_id)
        )
        db.add(
            orm.StoryDraftProjection(
                trip_id=trip_id,
                source_reconstruction_run_id=source_reconstruction_run_id,
                schema_version=STORY_DRAFT_PROJECTION_SCHEMA_VERSION,
                payload=payload,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()

    def photo_from_reconstruction_media(
        media: ReconstructionMediaResponse,
        asset_ids_by_media: dict[UUID, dict[str, UUID]],
    ) -> dict[str, object]:
        payload = media.model_dump(mode="json", by_alias=True)
        payload["thumbnailUrl"] = None
        payload["previewUrl"] = None
        asset_ids = asset_ids_by_media.get(media.id, {})
        thumbnail_id = asset_ids.get(MediaAssetType.THUMBNAIL.value)
        preview_id = asset_ids.get(MediaAssetType.DISPLAY.value)
        if thumbnail_id is not None:
            payload["thumbnailAssetId"] = str(thumbnail_id)
        if preview_id is not None:
            payload["previewAssetId"] = str(preview_id)
        return payload

    def story_photo_projection_payloads(
        db: DbSession,
        response: ReconstructionResponse,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        if response.latest_run is None:
            return [], []
        asset_ids_by_media = asset_ids_for_reconstruction(db, response)
        day_payloads: list[dict[str, object]] = []
        stop_payloads: list[dict[str, object]] = []
        for day in response.days:
            day_stops: list[dict[str, object]] = []
            for stop in day.stops:
                photos = [
                    photo_from_reconstruction_media(media, asset_ids_by_media)
                    for moment in stop.moments
                    for media in moment.media
                ]
                if not photos:
                    continue
                stop_payload = {
                    "id": str(stop.id),
                    "dayId": str(day.id),
                    "position": stop.position,
                    "displayPosition": stop.display_position,
                    "title": stop.title,
                    "placeName": stop.place_name,
                    "photos": photos,
                }
                day_stops.append(stop_payload)
                stop_payloads.append(
                    {
                        "dayId": str(day.id),
                        "stopId": str(stop.id),
                        "sourceReconstructionRunId": str(response.latest_run.id),
                        "schemaVersion": STORY_PHOTO_PROJECTION_SCHEMA_VERSION,
                        "stops": [stop_payload],
                    }
                )
            day_payloads.append(
                {
                    "dayId": str(day.id),
                    "sourceReconstructionRunId": str(response.latest_run.id),
                    "schemaVersion": STORY_PHOTO_PROJECTION_SCHEMA_VERSION,
                    "stops": day_stops,
                }
            )
        return day_payloads, stop_payloads

    def save_story_photo_projections(
        db: DbSession,
        *,
        trip_id: UUID,
        source_reconstruction_run_id: UUID,
        response: ReconstructionResponse,
    ) -> None:
        now = datetime.now(UTC)
        db.execute(
            delete(orm.StoryDayPhotoProjection).where(
                orm.StoryDayPhotoProjection.trip_id == trip_id
            )
        )
        db.execute(
            delete(orm.StoryStopPhotoProjection).where(
                orm.StoryStopPhotoProjection.trip_id == trip_id
            )
        )
        day_payloads, stop_payloads = story_photo_projection_payloads(db, response)
        for payload in day_payloads:
            day_id = UUID(str(payload["dayId"]))
            payload["tripId"] = str(trip_id)
            db.add(
                orm.StoryDayPhotoProjection(
                    trip_id=trip_id,
                    trip_day_id=day_id,
                    source_reconstruction_run_id=source_reconstruction_run_id,
                    schema_version=STORY_PHOTO_PROJECTION_SCHEMA_VERSION,
                    payload=payload,
                    created_at=now,
                    updated_at=now,
                )
            )
        for payload in stop_payloads:
            payload["tripId"] = str(trip_id)
            db.add(
                orm.StoryStopPhotoProjection(
                    trip_id=trip_id,
                    trip_day_id=UUID(str(payload["dayId"])),
                    stop_id=UUID(str(payload["stopId"])),
                    source_reconstruction_run_id=source_reconstruction_run_id,
                    schema_version=STORY_PHOTO_PROJECTION_SCHEMA_VERSION,
                    payload=payload,
                    created_at=now,
                    updated_at=now,
                )
            )
        db.commit()

    def rebuild_story_projections(db: DbSession, trip_id: UUID) -> None:
        response = reconstruction_response(db, trip_id)
        if response.latest_run is None:
            return
        save_story_draft_projection(
            db,
            trip_id=trip_id,
            source_reconstruction_run_id=response.latest_run.id,
            payload=story_draft_projection_payload(db, response),
        )
        save_story_photo_projections(
            db,
            trip_id=trip_id,
            source_reconstruction_run_id=response.latest_run.id,
            response=response,
        )

    def cached_download_urls_for_assets(
        db: DbSession, asset_ids: set[UUID]
    ) -> dict[UUID, str | None]:
        if not asset_ids:
            return {}
        now = datetime.now(UTC)
        refresh_after = now + DOWNLOAD_GRANT_REFRESH_WINDOW
        grants = {
            grant.asset_id: grant
            for grant in db.execute(
                select(orm.AssetDownloadGrant).where(
                    orm.AssetDownloadGrant.asset_id.in_(asset_ids),
                    orm.AssetDownloadGrant.expires_at > refresh_after,
                )
            ).scalars()
        }
        urls: dict[UUID, str | None] = {
            asset_id: grants[asset_id].download_url for asset_id in asset_ids if asset_id in grants
        }
        missing_ids = asset_ids - set(urls)
        if not missing_ids:
            return urls
        assets = list(
            db.execute(select(orm.MediaAsset).where(orm.MediaAsset.id.in_(missing_ids))).scalars()
        )
        db.execute(
            delete(orm.AssetDownloadGrant).where(orm.AssetDownloadGrant.asset_id.in_(missing_ids))
        )
        for asset in assets:
            try:
                grant = app.state.blob_store.create_download_grant(
                    DownloadGrantRequest(blob_ref=blob_ref_for_media_asset(asset))
                )
            except BlobNotFoundError:
                urls[asset.id] = None
                continue
            urls[asset.id] = grant.url
            db.add(
                orm.AssetDownloadGrant(
                    asset_id=asset.id,
                    asset_type=asset.asset_type,
                    download_url=grant.url,
                    expires_at=grant.expires_at,
                    created_at=now,
                    updated_at=now,
                )
            )
        db.commit()
        return urls

    def hydrate_story_photo_projection(
        db: DbSession, payload: dict[str, object]
    ) -> StoryPhotoProjectionResponse:
        hydrated = json.loads(json.dumps(payload))
        asset_ids: set[UUID] = set()
        media_refs: list[tuple[dict[str, object], str, UUID]] = []
        for stop in hydrated.get("stops", []):
            if not isinstance(stop, dict):
                continue
            for photo in stop.get("photos", []):
                if not isinstance(photo, dict):
                    continue
                for asset_key, url_key in (
                    ("thumbnailAssetId", "thumbnailUrl"),
                    ("previewAssetId", "previewUrl"),
                ):
                    asset_id = photo.get(asset_key)
                    if asset_id is None:
                        continue
                    try:
                        asset_uuid = UUID(str(asset_id))
                    except ValueError:
                        continue
                    asset_ids.add(asset_uuid)
                    media_refs.append((photo, url_key, asset_uuid))
        urls = cached_download_urls_for_assets(db, asset_ids)
        for photo, url_key, asset_id in media_refs:
            photo[url_key] = urls.get(asset_id)
        return StoryPhotoProjectionResponse.model_validate(hydrated)

    def latest_run_for_trip_or_none(db: DbSession, trip_id: UUID) -> orm.ReconstructionRun | None:
        return db.execute(
            select(orm.ReconstructionRun)
            .where(orm.ReconstructionRun.trip_id == trip_id)
            .order_by(orm.ReconstructionRun.created_at.desc(), orm.ReconstructionRun.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def story_draft_projection_response(db: DbSession, trip_id: UUID) -> ReconstructionResponse:
        latest_run = db.execute(
            select(orm.ReconstructionRun)
            .where(orm.ReconstructionRun.trip_id == trip_id)
            .order_by(orm.ReconstructionRun.created_at.desc(), orm.ReconstructionRun.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if latest_run is None:
            return reconstruction_response(db, trip_id)
        projection = db.execute(
            select(orm.StoryDraftProjection).where(
                orm.StoryDraftProjection.trip_id == trip_id,
                orm.StoryDraftProjection.source_reconstruction_run_id == latest_run.id,
                orm.StoryDraftProjection.schema_version == STORY_DRAFT_PROJECTION_SCHEMA_VERSION,
            )
        ).scalar_one_or_none()
        if projection is not None:
            return hydrate_story_draft_projection(db, projection.payload)

        response = reconstruction_response(db, trip_id)
        payload = story_draft_projection_payload(db, response)
        save_story_draft_projection(
            db,
            trip_id=trip_id,
            source_reconstruction_run_id=latest_run.id,
            payload=payload,
        )
        return hydrate_story_draft_projection(db, payload)

    @app.post("/trips/{trip_id}/reconstruction-runs", response_model=ReconstructionResponse)
    def start_reconstruction(
        trip_id: UUID,
        request: Request,
        actor: AuthenticatedActor = Depends(current_actor),
        db: DbSession = Depends(db_session),
    ) -> ReconstructionResponse:
        require_csrf(request)
        trip = db.get(orm.Trip, trip_id)
        if trip is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
        member = require_member_for_actor(db, trip_id, actor)
        if member.role not in {TripMemberRole.OWNER.value, TripMemberRole.EDITOR.value}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
        invalidate_story_draft_projection(db, trip_id)
        reconstruct_trip(db=db, trip=trip, geocoder=app.state.geocoder)
        response = reconstruction_response(db, trip_id)
        if response.latest_run is not None:
            save_story_draft_projection(
                db,
                trip_id=trip_id,
                source_reconstruction_run_id=response.latest_run.id,
                payload=story_draft_projection_payload(db, response),
            )
            save_story_photo_projections(
                db,
                trip_id=trip_id,
                source_reconstruction_run_id=response.latest_run.id,
                response=response,
            )
        return response

    @app.get("/trips/{trip_id}/reconstruction", response_model=ReconstructionResponse)
    def get_reconstruction(
        trip_id: UUID,
        actor: AuthenticatedActor = Depends(current_actor),
        db: DbSession = Depends(db_session),
    ) -> ReconstructionResponse:
        require_member_for_actor(db, trip_id, actor)
        return reconstruction_response(db, trip_id)

    @app.get("/trips/{trip_id}/story-draft-projection", response_model=ReconstructionResponse)
    def get_story_draft_projection(
        trip_id: UUID,
        actor: AuthenticatedActor = Depends(current_actor),
        db: DbSession = Depends(db_session),
    ) -> ReconstructionResponse:
        require_member_for_actor(db, trip_id, actor)
        return story_draft_projection_response(db, trip_id)

    @app.get(
        "/trips/{trip_id}/story-day-photos/{day_id}",
        response_model=StoryPhotoProjectionResponse,
    )
    def get_story_day_photos(
        trip_id: UUID,
        day_id: UUID,
        actor: AuthenticatedActor = Depends(current_actor),
        db: DbSession = Depends(db_session),
    ) -> StoryPhotoProjectionResponse:
        require_member_for_actor(db, trip_id, actor)
        latest_run = latest_run_for_trip_or_none(db, trip_id)
        if latest_run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not found")
        projection = db.execute(
            select(orm.StoryDayPhotoProjection).where(
                orm.StoryDayPhotoProjection.trip_id == trip_id,
                orm.StoryDayPhotoProjection.trip_day_id == day_id,
                orm.StoryDayPhotoProjection.source_reconstruction_run_id == latest_run.id,
                orm.StoryDayPhotoProjection.schema_version == STORY_PHOTO_PROJECTION_SCHEMA_VERSION,
            )
        ).scalar_one_or_none()
        if projection is None:
            response = story_draft_projection_response(db, trip_id)
            save_story_photo_projections(
                db,
                trip_id=trip_id,
                source_reconstruction_run_id=latest_run.id,
                response=response,
            )
            projection = db.execute(
                select(orm.StoryDayPhotoProjection).where(
                    orm.StoryDayPhotoProjection.trip_id == trip_id,
                    orm.StoryDayPhotoProjection.trip_day_id == day_id,
                    orm.StoryDayPhotoProjection.source_reconstruction_run_id == latest_run.id,
                    orm.StoryDayPhotoProjection.schema_version
                    == STORY_PHOTO_PROJECTION_SCHEMA_VERSION,
                )
            ).scalar_one_or_none()
        if projection is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story day not found")
        return hydrate_story_photo_projection(db, projection.payload)

    @app.get(
        "/trips/{trip_id}/story-stop-photos/{stop_id}",
        response_model=StoryPhotoProjectionResponse,
    )
    def get_story_stop_photos(
        trip_id: UUID,
        stop_id: UUID,
        actor: AuthenticatedActor = Depends(current_actor),
        db: DbSession = Depends(db_session),
    ) -> StoryPhotoProjectionResponse:
        require_member_for_actor(db, trip_id, actor)
        latest_run = latest_run_for_trip_or_none(db, trip_id)
        if latest_run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not found")
        projection = db.execute(
            select(orm.StoryStopPhotoProjection).where(
                orm.StoryStopPhotoProjection.trip_id == trip_id,
                orm.StoryStopPhotoProjection.stop_id == stop_id,
                orm.StoryStopPhotoProjection.source_reconstruction_run_id == latest_run.id,
                orm.StoryStopPhotoProjection.schema_version
                == STORY_PHOTO_PROJECTION_SCHEMA_VERSION,
            )
        ).scalar_one_or_none()
        if projection is None:
            response = story_draft_projection_response(db, trip_id)
            save_story_photo_projections(
                db,
                trip_id=trip_id,
                source_reconstruction_run_id=latest_run.id,
                response=response,
            )
            projection = db.execute(
                select(orm.StoryStopPhotoProjection).where(
                    orm.StoryStopPhotoProjection.trip_id == trip_id,
                    orm.StoryStopPhotoProjection.stop_id == stop_id,
                    orm.StoryStopPhotoProjection.source_reconstruction_run_id == latest_run.id,
                    orm.StoryStopPhotoProjection.schema_version
                    == STORY_PHOTO_PROJECTION_SCHEMA_VERSION,
                )
            ).scalar_one_or_none()
        if projection is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Story stop not found"
            )
        return hydrate_story_photo_projection(db, projection.payload)

    @app.post("/trips/{trip_id}/publications", response_model=PublicationResponse)
    def create_publication(
        trip_id: UUID,
        request: Request,
        actor: AuthenticatedActor = Depends(current_actor),
        db: DbSession = Depends(db_session),
    ) -> PublicationResponse:
        require_csrf(request)
        member = require_member_for_actor(db, trip_id, actor)
        rate_limit_action(
            request,
            "publication_rate_limiter",
            "create-publication",
            f"{trip_id}:{member.id}",
        )
        if member.role not in {TripMemberRole.OWNER.value, TripMemberRole.EDITOR.value}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
        trip = db.get(orm.Trip, trip_id)
        if trip is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
        source_run_id = validate_publishable(db, trip_id)
        version_number = next_story_version_number(db, trip_id)
        version = orm.StoryVersion(
            trip_id=trip_id,
            version_number=version_number,
            state=StoryVersionState.PENDING.value,
            title=trip.title,
            asset_prefix=f"trips/{trip_id}/story/v{version_number}",
            source_reconstruction_run_id=source_run_id,
            created_by_member_id=member.id,
            created_by_user_id=actor.user.id if actor.user is not None else None,
            audit={
                "requestedAt": datetime.now(UTC).isoformat(),
                "requestedByMemberId": str(member.id),
            },
        )
        db.add(version)
        db.flush()
        token = secrets.token_urlsafe(32)
        link = orm.ShareLink(
            trip_id=trip_id,
            story_version_id=version.id,
            token_hash=hash_token(token),
            status=ShareLinkStatus.ACTIVE.value,
            created_by_user_id=actor.user.id if actor.user is not None else None,
        )
        db.add(link)
        db.add(
            orm.ProcessingJob(
                job_type=ProcessingJobType.PUBLICATION.value,
                target_type=ProcessingTargetType.STORY_PUBLICATION.value,
                target_id=version.id,
                priority=40,
                idempotency_key=f"publish-story:{version.id}",
            )
        )
        db.commit()
        return PublicationResponse(
            version=story_version_response(version),
            shareLink=share_link_response(link, share_url(request, token)),
        )

    @app.get("/trips/{trip_id}/publications", response_model=PublicationsListResponse)
    def list_publications(
        trip_id: UUID,
        actor: AuthenticatedActor = Depends(current_actor),
        db: DbSession = Depends(db_session),
    ) -> PublicationsListResponse:
        member = require_member_for_actor(db, trip_id, actor)
        if member.role not in {TripMemberRole.OWNER.value, TripMemberRole.EDITOR.value}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
        versions = list(
            db.scalars(
                select(orm.StoryVersion)
                .where(orm.StoryVersion.trip_id == trip_id)
                .order_by(orm.StoryVersion.version_number.desc())
            )
        )
        links = list(
            db.scalars(
                select(orm.ShareLink)
                .where(orm.ShareLink.trip_id == trip_id)
                .order_by(orm.ShareLink.created_at.desc(), orm.ShareLink.id.desc())
            )
        )
        return PublicationsListResponse(
            versions=[story_version_response(version) for version in versions],
            shareLinks=[share_link_response(link) for link in links],
        )

    @app.delete("/share-links/{share_link_id}", status_code=status.HTTP_204_NO_CONTENT)
    def revoke_share_link(
        share_link_id: UUID,
        request: Request,
        actor: AuthenticatedActor = Depends(current_actor),
        db: DbSession = Depends(db_session),
    ) -> Response:
        require_csrf(request)
        link = db.get(orm.ShareLink, share_link_id)
        if link is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not found")
        member = require_member_for_actor(db, link.trip_id, actor)
        if member.role not in {TripMemberRole.OWNER.value, TripMemberRole.EDITOR.value}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story not found")
        now = datetime.now(UTC)
        link.status = ShareLinkStatus.REVOKED.value
        link.revoked_at = now
        link.updated_at = now
        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/trips/{trip_id}/unpublish", status_code=status.HTTP_204_NO_CONTENT)
    def unpublish_trip(
        trip_id: UUID,
        request: Request,
        actor: AuthenticatedActor = Depends(current_actor),
        db: DbSession = Depends(db_session),
    ) -> Response:
        require_csrf(request)
        member = require_member_for_actor(db, trip_id, actor)
        if member.role not in {TripMemberRole.OWNER.value, TripMemberRole.EDITOR.value}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
        now = datetime.now(UTC)
        for link in db.scalars(
            select(orm.ShareLink).where(
                orm.ShareLink.trip_id == trip_id,
                orm.ShareLink.status == ShareLinkStatus.ACTIVE.value,
                orm.ShareLink.revoked_at.is_(None),
            )
        ):
            link.status = ShareLinkStatus.REVOKED.value
            link.revoked_at = now
            link.updated_at = now
        trip = db.get(orm.Trip, trip_id)
        if trip is not None:
            trip.visibility = TripVisibility.PRIVATE.value
            trip.updated_at = now
        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/public/shares/{token}", response_model=PublicStoryResponse)
    def get_public_story(
        request: Request, token: str, db: DbSession = Depends(db_session)
    ) -> PublicStoryResponse:
        link = active_share_link_for_token(db, token)
        version = db.get(orm.StoryVersion, link.story_version_id)
        if version is None or version.state == StoryVersionState.FAILED.value:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story unavailable")
        if version.state != StoryVersionState.PUBLISHED.value:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Story is publishing"
            )
        try:
            manifest = cached_public_manifest(version)
        except PublicationError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.safe_message
            ) from exc
        db.commit()
        return public_story_response(request, token, link, version, manifest)

    @app.get("/public/shares/{token}/assets/{asset_id}")
    def get_public_story_asset(
        token: str,
        asset_id: str,
        db: DbSession = Depends(db_session),
    ) -> StreamingResponse:
        link = active_share_link_for_token(db, token)
        version = db.get(orm.StoryVersion, link.story_version_id)
        if version is None or version.state != StoryVersionState.PUBLISHED.value:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Story unavailable")
        try:
            manifest = cached_public_manifest(version)
            asset = public_asset_for_id(manifest, asset_id)
            blob_ref = blob_ref_for_public_asset(asset)
            if blob_ref.store_alias != "story_published":
                raise PublicationError("publication_invalid", "Story asset is invalid")
        except PublicationError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=exc.safe_message
            ) from exc
        except BlobNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found"
            ) from exc
        db.commit()

        def body() -> Iterator[bytes]:
            with app.state.blob_store.open_reader(blob_ref) as reader:
                while True:
                    chunk = reader.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk

        return StreamingResponse(
            body(),
            media_type=blob_ref.content_type or "application/octet-stream",
            headers={"cache-control": "public, max-age=86400"},
        )

    @app.post("/trips/{trip_id}/edit-operations", response_model=EditOperationResponse)
    def create_edit_operation(
        trip_id: UUID,
        payload: EditOperationRequest,
        request: Request,
        actor: AuthenticatedActor = Depends(current_actor),
        db: DbSession = Depends(db_session),
    ) -> EditOperationResponse:
        require_csrf(request)
        member = require_member_for_actor(db, trip_id, actor)
        operation = apply_edit_operation(
            db,
            trip_id=trip_id,
            actor=actor,
            member=member,
            payload=payload,
        )
        return edit_operation_response(operation)

    @app.post("/trips/{trip_id}/edit-operations/undo", response_model=EditOperationResponse)
    def undo_edit_operation(
        trip_id: UUID,
        request: Request,
        actor: AuthenticatedActor = Depends(current_actor),
        db: DbSession = Depends(db_session),
    ) -> EditOperationResponse:
        require_csrf(request)
        member = require_member_for_actor(db, trip_id, actor)
        operation = undo_latest_edit_operation(
            db,
            trip_id=trip_id,
            actor=actor,
            member=member,
        )
        return edit_operation_response(operation)

    @app.get("/blob-download/{token}")
    def download_blob(token: str) -> StreamingResponse:
        try:
            blob_ref = app.state.blob_store.verify_download_token(token)
            metadata = app.state.blob_store.stat(blob_ref)
        except InvalidGrantError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except BlobNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Blob not found"
            ) from exc

        def body() -> Iterator[bytes]:
            with app.state.blob_store.open_reader(blob_ref) as reader:
                while True:
                    chunk = reader.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk

        return StreamingResponse(
            body(),
            media_type=metadata.content_type or "application/octet-stream",
            headers={"cache-control": "private, max-age=60"},
        )

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


def local_storage_usage(settings: Settings) -> dict[str, Any]:
    aliases: dict[str, dict[str, int]] = {}
    total_bytes = 0
    total_files = 0
    root = settings.blob_dir
    for alias in sorted(settings.store_aliases):
        alias_dir = root / alias
        alias_bytes = 0
        alias_files = 0
        if alias_dir.exists():
            for dirpath, _, filenames in os.walk(alias_dir, followlinks=False):
                base = os.fspath(dirpath)
                for filename in filenames:
                    path = os.path.join(base, filename)
                    try:
                        stat_result = os.stat(path, follow_symlinks=False)
                    except OSError:
                        continue
                    if not os.path.isfile(path):
                        continue
                    alias_bytes += stat_result.st_size
                    alias_files += 1
        aliases[alias] = {"bytes": alias_bytes, "files": alias_files}
        total_bytes += alias_bytes
        total_files += alias_files
    return {
        "root": str(root),
        "totalBytes": total_bytes,
        "totalFiles": total_files,
        "aliases": aliases,
    }


app = create_app()


def run() -> None:
    uvicorn.run("tripweave.entrypoints.api.main:app", host="0.0.0.0", port=8000)
