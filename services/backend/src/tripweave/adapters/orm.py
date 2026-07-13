from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import UserDefinedType

from tripweave.domain.enums import (
    InvitationStatus,
    LocationSource,
    MediaAssetType,
    MediaType,
    MediaVisibility,
    ProcessingJobState,
    ProcessingJobType,
    ProcessingState,
    ProcessingTargetType,
    TimeSource,
    TripMemberRole,
    TripStatus,
    TripVisibility,
    UploadState,
)

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class GeographyPoint(UserDefinedType[object]):
    cache_ok = True

    def get_col_spec(self, **_kw: object) -> str:
        return "geography(Point,4326)"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def enum_values(enum_type: type[StrEnum]) -> str:
    return ", ".join(f"'{item.value}'" for item in enum_type.__members__.values())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_normalized"),
        CheckConstraint("length(email) > 3", name="email_min_length"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Trip(Base, TimestampMixin):
    __tablename__ = "trips"
    __table_args__ = (
        CheckConstraint("day_cutoff_hour >= 0 AND day_cutoff_hour <= 23", name="day_cutoff_hour"),
        CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date", name="date_order"
        ),
        CheckConstraint(f"status IN ({enum_values(TripStatus)})", name="status"),
        CheckConstraint(f"visibility IN ({enum_values(TripVisibility)})", name="visibility"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    timezone_id: Mapped[str] = mapped_column(String(100), nullable=False)
    day_cutoff_hour: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("4"))
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default=text("'draft'"))
    visibility: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'private'")
    )
    created_by: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class TripMember(Base):
    __tablename__ = "trip_members"
    __table_args__ = (
        CheckConstraint(f"role IN ({enum_values(TripMemberRole)})", name="role"),
        CheckConstraint(
            "user_id IS NOT NULL OR display_name IS NOT NULL", name="guest_display_name"
        ),
        UniqueConstraint("id", "trip_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TripInvitation(Base):
    __tablename__ = "trip_invitations"
    __table_args__ = (
        CheckConstraint(f"role IN ({enum_values(TripMemberRole)})", name="role"),
        CheckConstraint(f"status IN ({enum_values(InvitationStatus)})", name="status"),
        CheckConstraint("email IS NULL OR email = lower(email)", name="email_normalized"),
        CheckConstraint(
            "use_count >= 0 AND max_uses > 0 AND use_count <= max_uses", name="use_count"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str | None] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'pending'")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_member_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trip_members.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class GuestSession(Base):
    __tablename__ = "guest_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["member_id", "trip_id"],
            ["trip_members.id", "trip_members.trip_id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    member_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class UploadSession(Base):
    __tablename__ = "upload_sessions"
    __table_args__ = (
        CheckConstraint(f"state IN ({enum_values(UploadState)})", name="state"),
        CheckConstraint(
            "declared_file_count IS NULL OR declared_file_count >= 0", name="file_count"
        ),
        CheckConstraint(
            "declared_total_bytes IS NULL OR declared_total_bytes >= 0", name="total_bytes"
        ),
        ForeignKeyConstraint(
            ["member_id", "trip_id"],
            ["trip_members.id", "trip_members.trip_id"],
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    member_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'registering'")
    )
    declared_file_count: Mapped[int | None] = mapped_column(Integer)
    declared_total_bytes: Mapped[int | None] = mapped_column(BigInteger)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transfer_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transferred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class UploadFile(Base):
    __tablename__ = "upload_files"
    __table_args__ = (
        CheckConstraint(f"state IN ({enum_values(UploadState)})", name="state"),
        CheckConstraint("declared_byte_size IS NULL OR declared_byte_size >= 0", name="byte_size"),
        UniqueConstraint("store_alias", "object_key"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    upload_session_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("upload_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    media_item_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("media_items.id", ondelete="SET NULL")
    )
    state: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'registered'")
    )
    original_filename: Mapped[str | None] = mapped_column(Text)
    declared_byte_size: Mapped[int | None] = mapped_column(BigInteger)
    declared_mime_type: Mapped[str | None] = mapped_column(String(255))
    detected_mime_type: Mapped[str | None] = mapped_column(String(255))
    store_alias: Mapped[str] = mapped_column(String(100), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    transfer_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transferred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class MediaItem(Base, TimestampMixin):
    __tablename__ = "media_items"
    __table_args__ = (
        CheckConstraint(f"media_type IN ({enum_values(MediaType)})", name="media_type"),
        CheckConstraint(f"time_source IN ({enum_values(TimeSource)})", name="time_source"),
        CheckConstraint(
            f"location_source IN ({enum_values(LocationSource)})", name="location_source"
        ),
        CheckConstraint(
            f"processing_state IN ({enum_values(ProcessingState)})", name="processing_state"
        ),
        CheckConstraint(f"visibility IN ({enum_values(MediaVisibility)})", name="visibility"),
        CheckConstraint("byte_size IS NULL OR byte_size >= 0", name="byte_size"),
        CheckConstraint(
            "time_confidence IS NULL OR (time_confidence >= 0 AND time_confidence <= 1)",
            name="time_confidence",
        ),
        CheckConstraint(
            "location_confidence IS NULL OR "
            "(location_confidence >= 0 AND location_confidence <= 1)",
            name="location_confidence",
        ),
        UniqueConstraint("original_store_alias", "original_object_key"),
        ForeignKeyConstraint(
            ["contributor_member_id", "trip_id"],
            ["trip_members.id", "trip_members.trip_id"],
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    contributor_member_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    media_type: Mapped[str] = mapped_column(String(40), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(Text)
    declared_mime_type: Mapped[str | None] = mapped_column(String(255))
    detected_mime_type: Mapped[str | None] = mapped_column(String(255))
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    original_store_alias: Mapped[str] = mapped_column(String(100), nullable=False)
    original_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    original_captured_at_local: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    original_captured_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_utc_offset_minutes: Mapped[int | None] = mapped_column(Integer)
    effective_captured_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_location: Mapped[object | None] = mapped_column(GeographyPoint)
    effective_location: Mapped[object | None] = mapped_column(GeographyPoint)
    time_source: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'unknown'")
    )
    location_source: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'unknown'")
    )
    time_confidence: Mapped[float | None] = mapped_column(Float)
    location_confidence: Mapped[float | None] = mapped_column(Float)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    perceptual_hash: Mapped[str | None] = mapped_column(String(255))
    original_metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    processing_state: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'pending'")
    )
    visibility: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'private'")
    )
    include_in_story: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    caption: Mapped[str | None] = mapped_column(Text)
    memo: Mapped[str | None] = mapped_column(Text)
    user_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    assets: Mapped[list[MediaAsset]] = relationship(back_populates="media_item")


class MediaAsset(Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        CheckConstraint(f"asset_type IN ({enum_values(MediaAssetType)})", name="asset_type"),
        CheckConstraint("width IS NULL OR width > 0", name="width"),
        CheckConstraint("height IS NULL OR height > 0", name="height"),
        CheckConstraint("byte_size IS NULL OR byte_size >= 0", name="byte_size"),
        UniqueConstraint("store_alias", "object_key"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    media_item_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("media_items.id", ondelete="CASCADE"), nullable=False
    )
    asset_type: Mapped[str] = mapped_column(String(40), nullable=False)
    store_alias: Mapped[str] = mapped_column(String(100), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    checksum: Mapped[str | None] = mapped_column(Text)
    metadata_stripped: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    media_item: Mapped[MediaItem] = relationship(back_populates="assets")


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        CheckConstraint(f"job_type IN ({enum_values(ProcessingJobType)})", name="job_type"),
        CheckConstraint(
            f"target_type IN ({enum_values(ProcessingTargetType)})", name="target_type"
        ),
        CheckConstraint(f"state IN ({enum_values(ProcessingJobState)})", name="state"),
        CheckConstraint("priority >= 0", name="priority"),
        CheckConstraint("attempts >= 0", name="attempts"),
        CheckConstraint("max_attempts > 0", name="max_attempts"),
        CheckConstraint("attempts <= max_attempts", name="attempt_budget"),
        UniqueConstraint("idempotency_key"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    job_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False, server_default=text("'pending'"))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(160))
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


Index("ix_sessions_user_id", Session.user_id)
Index("ix_trips_created_by", Trip.created_by)
Index("ix_trip_members_trip_id", TripMember.trip_id)
Index("ix_trip_members_user_id", TripMember.user_id)
Index(
    "uq_trip_members_active_user",
    TripMember.trip_id,
    TripMember.user_id,
    unique=True,
    postgresql_where=TripMember.removed_at.is_(None),
)
Index("ix_trip_invitations_trip_email", TripInvitation.trip_id, TripInvitation.email)
Index("ix_guest_sessions_trip_id", GuestSession.trip_id)
Index("ix_guest_sessions_member_id", GuestSession.member_id)
Index("ix_upload_sessions_trip_id", UploadSession.trip_id)
Index("ix_upload_sessions_member_id", UploadSession.member_id)
Index("ix_upload_files_upload_session_id", UploadFile.upload_session_id)
Index("ix_upload_files_media_item_id", UploadFile.media_item_id)
Index("ix_media_items_trip_id", MediaItem.trip_id)
Index("ix_media_items_contributor_member_id", MediaItem.contributor_member_id)
Index("ix_media_items_effective_captured_at_utc", MediaItem.effective_captured_at_utc)
Index("ix_media_items_sha256", MediaItem.sha256)
Index("ix_media_items_original_location_gist", MediaItem.original_location, postgresql_using="gist")
Index(
    "ix_media_items_effective_location_gist", MediaItem.effective_location, postgresql_using="gist"
)
Index("ix_media_assets_media_item_id", MediaAsset.media_item_id)
Index(
    "ix_processing_jobs_claimable",
    ProcessingJob.state,
    ProcessingJob.priority,
    ProcessingJob.run_after,
)
Index("ix_processing_jobs_target", ProcessingJob.target_type, ProcessingJob.target_id)
