# ruff: noqa: B008
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from tripweave.adapters import orm
from tripweave.adapters.blob_store_factory import create_blob_store
from tripweave.adapters.database import check_database, create_database_engine, get_postgis_version
from tripweave.adapters.local_blob_store import (
    BlobNotFoundError,
    BlobSizeExceededError,
    InvalidGrantError,
)
from tripweave.adapters.manual_geocoder import ManualGeocoder
from tripweave.adapters.reconstruction import reconstruct_trip
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
    InvitationStatus,
    MediaType,
    MediaVisibility,
    ProcessingJobState,
    ProcessingJobType,
    ProcessingState,
    ProcessingTargetType,
    TripMemberRole,
    TripStatus,
    TripVisibility,
    UploadState,
)
from tripweave.domain.storage import BlobRef, DownloadGrantRequest, UploadGrant, UploadGrantRequest
from tripweave.entrypoints.api.schemas import (
    AuthResponse,
    BlobRefResponse,
    CompleteUploadFileResponse,
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
    ReconstructionDayResponse,
    ReconstructionMomentResponse,
    ReconstructionResponse,
    ReconstructionRunResponse,
    ReconstructionStopResponse,
    RegisterRequest,
    ReviewItemResponse,
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
    app.state.blob_store = create_blob_store(resolved_settings)
    app.state.geocoder = ManualGeocoder()

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

    def invitation_url(request: Request, token: str) -> str:
        origin = request.headers.get("origin")
        if origin in resolved_settings.cors_origins:
            return f"{origin}/invite/{token}"
        return f"http://localhost:3000/invite/{token}"

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
        return trip_response(trip, member.role)

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
        require_owner_member(db, trip_id, auth.user.id)
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
        response: Response,
        db: DbSession = Depends(db_session),
    ) -> GuestMemberResponse:
        invitation = active_invitation_for_token(db, token)
        now = datetime.now(UTC)
        member = (
            db.get(orm.TripMember, invitation.accepted_member_id)
            if invitation.accepted_member_id is not None
            else None
        )
        if member is None:
            if invitation.use_count >= invitation.max_uses:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found"
                )
            member = orm.TripMember(
                trip_id=invitation.trip_id,
                user_id=None,
                role=invitation.role,
                display_name=payload.display_name.strip(),
                joined_at=now,
            )
            db.add(member)
            db.flush()
            invitation.accepted_member_id = member.id
            invitation.accepted_at = now
            invitation.use_count += 1
            invitation.status = InvitationStatus.ACCEPTED.value
        elif member.removed_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found"
            )
        else:
            guest = optional_guest(request, db)
            if guest is None or guest.member.id != member.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found"
                )
        secrets_value = new_session_secrets(resolved_settings.guest_session_lifetime_seconds)
        db.add(
            orm.GuestSession(
                trip_id=member.trip_id,
                member_id=member.id,
                token_hash=secrets_value.session_token_hash,
                expires_at=secrets_value.expires_at,
            )
        )
        db.commit()
        set_guest_cookies(response, secrets_value.session_token, secrets_value.csrf_token)
        return GuestMemberResponse(
            id=member.id,
            tripId=member.trip_id,
            displayName=member.display_name,
            role=member.role,
            csrfToken=secrets_value.csrf_token,
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

    def media_asset_response(asset: orm.MediaAsset) -> MediaAssetResponse:
        download_url: str | None = None
        try:
            download_url = app.state.blob_store.create_download_grant(
                DownloadGrantRequest(
                    blob_ref=BlobRef(store_alias=asset.store_alias, object_key=asset.object_key)
                )
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
        db: DbSession, media_item: orm.MediaItem, contributor: orm.TripMember
    ) -> MediaItemResponse:
        thumbnail = next(
            (asset for asset in media_item.assets if asset.asset_type == "thumbnail"),
            None,
        )
        dimensions = media_item.original_metadata_json.get("dimensions", {})
        width = dimensions.get("width") if isinstance(dimensions, dict) else None
        height = dimensions.get("height") if isinstance(dimensions, dict) else None
        return MediaItemResponse(
            id=media_item.id,
            filename=media_item.original_filename,
            processingState=media_item.processing_state,
            errorMessage=media_error_for(db, media_item.id),
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
        )

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
        if member.role not in {TripMemberRole.OWNER.value, TripMemberRole.EDITOR.value}:
            statement = statement.where(orm.MediaItem.contributor_member_id == member.id)
        rows = db.execute(statement).all()
        return MediaListResponse(
            media=[
                media_item_response(db, media_item, contributor) for media_item, contributor in rows
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
        return media_item_response(db, media_item, member)

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

        is_owner_editor = member.role in {TripMemberRole.OWNER.value, TripMemberRole.EDITOR.value}
        is_contributor_owner = media_item.contributor_member_id == member.id
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
        db.commit()
        contributor = db.get(orm.TripMember, media_item.contributor_member_id)
        if contributor is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
        return media_item_response(db, media_item, contributor)

    def reconstruction_response(db: DbSession, trip_id: UUID) -> ReconstructionResponse:
        latest_run = db.execute(
            select(orm.ReconstructionRun)
            .where(orm.ReconstructionRun.trip_id == trip_id)
            .order_by(orm.ReconstructionRun.created_at.desc(), orm.ReconstructionRun.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if latest_run is None:
            return ReconstructionResponse(latestRun=None, days=[], reviewItems=[])

        days = list(
            db.execute(
                select(orm.TripDay)
                .where(
                    orm.TripDay.trip_id == trip_id,
                    orm.TripDay.reconstruction_run_id == latest_run.id,
                )
                .order_by(orm.TripDay.position)
            ).scalars()
        )
        stops = list(
            db.execute(
                select(orm.Stop, orm.Place)
                .join(orm.Place, orm.Place.id == orm.Stop.place_id)
                .where(
                    orm.Stop.trip_id == trip_id,
                    orm.Stop.reconstruction_run_id == latest_run.id,
                )
                .order_by(orm.Stop.position)
            ).all()
        )
        moments = list(
            db.execute(
                select(orm.Moment)
                .where(
                    orm.Moment.trip_id == trip_id,
                    orm.Moment.reconstruction_run_id == latest_run.id,
                )
                .order_by(orm.Moment.position)
            ).scalars()
        )
        moment_media_rows = db.execute(
            select(orm.MomentMedia.moment_id, orm.Moment.stop_id, orm.MediaItem)
            .join(orm.Moment, orm.Moment.id == orm.MomentMedia.moment_id)
            .join(orm.MediaItem, orm.MediaItem.id == orm.MomentMedia.media_item_id)
            .where(
                orm.MomentMedia.trip_id == trip_id,
                orm.MomentMedia.reconstruction_run_id == latest_run.id,
            )
        ).all()
        contributors_by_moment: dict[UUID, set[UUID]] = {}
        media_count_by_moment: dict[UUID, int] = {}
        local_times_by_moment: dict[UUID, list[datetime]] = {}
        local_times_by_stop: dict[UUID, list[datetime]] = {}
        for moment_id, stop_id, media_item in moment_media_rows:
            contributor_id = media_item.contributor_member_id
            media_count_by_moment[moment_id] = media_count_by_moment.get(moment_id, 0) + 1
            contributors_by_moment.setdefault(moment_id, set()).add(contributor_id)
            local_capture = media_local_capture(media_item)
            if local_capture is not None:
                local_times_by_moment.setdefault(moment_id, []).append(local_capture)
                local_times_by_stop.setdefault(stop_id, []).append(local_capture)

        moments_by_stop: dict[UUID, list[ReconstructionMomentResponse]] = {}
        for moment in moments:
            contributors = contributors_by_moment.get(moment.id, set())
            moment_local_times = local_times_by_moment.get(moment.id, [])
            moments_by_stop.setdefault(moment.stop_id, []).append(
                ReconstructionMomentResponse(
                    id=moment.id,
                    position=moment.position,
                    startsAt=moment.starts_at_utc,
                    endsAt=moment.ends_at_utc,
                    startsAtLocal=min(moment_local_times) if moment_local_times else None,
                    endsAtLocal=max(moment_local_times) if moment_local_times else None,
                    mediaCount=media_count_by_moment.get(moment.id, 0),
                    contributorCount=len(contributors),
                )
            )

        stops_by_day: dict[UUID, list[ReconstructionStopResponse]] = {}
        for stop, place in stops:
            moment_items = moments_by_stop.get(stop.id, [])
            stop_local_times = local_times_by_stop.get(stop.id, [])
            media_count = sum(item.media_count for item in moment_items)
            contributor_count = sum(item.contributor_count for item in moment_items)
            stops_by_day.setdefault(stop.trip_day_id, []).append(
                ReconstructionStopResponse(
                    id=stop.id,
                    position=stop.position,
                    startsAt=stop.starts_at_utc,
                    endsAt=stop.ends_at_utc,
                    startsAtLocal=min(stop_local_times) if stop_local_times else None,
                    endsAtLocal=max(stop_local_times) if stop_local_times else None,
                    placeName=place.name,
                    mediaCount=media_count,
                    contributorCount=contributor_count,
                    moments=moment_items,
                )
            )

        review_items = list(
            db.execute(
                select(orm.ReviewItem)
                .where(
                    orm.ReviewItem.trip_id == trip_id,
                    orm.ReviewItem.reconstruction_run_id == latest_run.id,
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
                    position=day.position,
                    stops=stops_by_day.get(day.id, []),
                )
                for day in days
            ],
            reviewItems=[
                ReviewItemResponse(
                    id=item.id,
                    itemType=item.item_type,
                    status=item.status,
                    message=item.message,
                    mediaItemId=item.media_item_id,
                )
                for item in review_items
            ],
        )

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
        reconstruct_trip(db=db, trip=trip, geocoder=app.state.geocoder)
        return reconstruction_response(db, trip_id)

    @app.get("/trips/{trip_id}/reconstruction", response_model=ReconstructionResponse)
    def get_reconstruction(
        trip_id: UUID,
        actor: AuthenticatedActor = Depends(current_actor),
        db: DbSession = Depends(db_session),
    ) -> ReconstructionResponse:
        require_member_for_actor(db, trip_id, actor)
        return reconstruction_response(db, trip_id)

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


app = create_app()


def run() -> None:
    uvicorn.run("tripweave.entrypoints.api.main:app", host="0.0.0.0", port=8000)
