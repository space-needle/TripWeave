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
    EditOperationStatus,
    EditOperationType,
    InvitationStatus,
    LocationSource,
    MediaAssetType,
    MediaType,
    MediaVisibility,
    OriginalRetentionState,
    ProcessingJobState,
    ProcessingJobType,
    ProcessingState,
    ProcessingTargetType,
    ReconstructionRunState,
    ReconstructionSource,
    ReviewItemStatus,
    ReviewItemType,
    ReviewSeverity,
    RouteSource,
    ShareLinkStatus,
    SimilarityGroupType,
    StoryVersionState,
    SuggestionStatus,
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


class GeographyLineString(UserDefinedType[object]):
    cache_ok = True

    def get_col_spec(self, **_kw: object) -> str:
        return "geography(LineString,4326)"


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
        CheckConstraint(
            f"original_retention_state IN ({enum_values(OriginalRetentionState)})",
            name="original_retention_state",
        ),
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
    capture_device_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("capture_devices.id", ondelete="SET NULL")
    )
    media_type: Mapped[str] = mapped_column(String(40), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(Text)
    declared_mime_type: Mapped[str | None] = mapped_column(String(255))
    detected_mime_type: Mapped[str | None] = mapped_column(String(255))
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    original_store_alias: Mapped[str] = mapped_column(String(100), nullable=False)
    original_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    original_retention_state: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'retained'")
    )
    original_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class CaptureDevice(Base, TimestampMixin):
    __tablename__ = "capture_devices"
    __table_args__ = (UniqueConstraint("trip_id", "device_key"),)

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    contributor_member_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trip_members.id", ondelete="SET NULL")
    )
    device_key: Mapped[str] = mapped_column(String(160), nullable=False)
    make: Mapped[str | None] = mapped_column(String(160))
    model: Mapped[str | None] = mapped_column(String(160))
    software: Mapped[str | None] = mapped_column(String(160))
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    accepted_clock_offset_seconds: Mapped[int | None] = mapped_column(Integer)
    accepted_suggestion_id: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True))


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


class GeneratedRecordMixin(TimestampMixin):
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    algorithm_version: Mapped[str] = mapped_column(String(80), nullable=False)
    reconstruction_run_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("reconstruction_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class SimilarityGroup(Base, GeneratedRecordMixin):
    __tablename__ = "similarity_groups"
    __table_args__ = (
        CheckConstraint(f"source IN ({enum_values(ReconstructionSource)})", name="source"),
        CheckConstraint(f"group_type IN ({enum_values(SimilarityGroupType)})", name="group_type"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    group_type: Mapped[str] = mapped_column(String(40), nullable=False)
    representative_media_item_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("media_items.id", ondelete="SET NULL")
    )
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)


class SimilarityGroupMember(Base):
    __tablename__ = "similarity_group_members"
    __table_args__ = (
        CheckConstraint(
            "similarity_score IS NULL OR (similarity_score >= 0 AND similarity_score <= 1)",
            name="similarity_score",
        ),
        CheckConstraint(
            "technical_score IS NULL OR (technical_score >= 0 AND technical_score <= 1)",
            name="technical_score",
        ),
        UniqueConstraint("similarity_group_id", "media_item_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    similarity_group_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("similarity_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    media_item_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("media_items.id", ondelete="CASCADE"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    similarity_score: Mapped[float | None] = mapped_column(Float)
    technical_score: Mapped[float | None] = mapped_column(Float)
    is_representative: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    user_selected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    signals: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class DeviceClockOffsetSuggestion(Base, GeneratedRecordMixin):
    __tablename__ = "device_clock_offset_suggestions"
    __table_args__ = (
        CheckConstraint(f"source IN ({enum_values(ReconstructionSource)})", name="source"),
        CheckConstraint(f"status IN ({enum_values(SuggestionStatus)})", name="status"),
        CheckConstraint("support_count >= 0", name="support_count"),
        CheckConstraint("dispersion_seconds >= 0", name="dispersion_seconds"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    capture_device_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("capture_devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    offset_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    support_count: Mapped[int] = mapped_column(Integer, nullable=False)
    dispersion_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default=text("'open'"))
    evidence: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReconstructionRun(Base, TimestampMixin):
    __tablename__ = "reconstruction_runs"
    __table_args__ = (
        CheckConstraint(f"state IN ({enum_values(ReconstructionRunState)})", name="state"),
        CheckConstraint(f"source IN ({enum_values(ReconstructionSource)})", name="source"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(40), nullable=False, server_default=text("'running'"))
    source: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'automation'")
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    algorithm_version: Mapped[str] = mapped_column(String(80), nullable=False)
    algorithm_config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    user_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    summary: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)


class TripDay(Base, GeneratedRecordMixin):
    __tablename__ = "trip_days"
    __table_args__ = (
        CheckConstraint(f"source IN ({enum_values(ReconstructionSource)})", name="source"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence"
        ),
        UniqueConstraint("trip_id", "day_date", "reconstruction_run_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    day_date: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Place(Base, GeneratedRecordMixin):
    __tablename__ = "places"
    __table_args__ = (
        CheckConstraint(f"source IN ({enum_values(ReconstructionSource)})", name="source"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str | None] = mapped_column(String(255))
    centroid: Mapped[object | None] = mapped_column(GeographyPoint)


class Stop(Base, GeneratedRecordMixin):
    __tablename__ = "stops"
    __table_args__ = (
        CheckConstraint(f"source IN ({enum_values(ReconstructionSource)})", name="source"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    trip_day_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trip_days.id", ondelete="CASCADE"), nullable=False
    )
    place_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("places.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    centroid: Mapped[object | None] = mapped_column(GeographyPoint)


class Moment(Base, GeneratedRecordMixin):
    __tablename__ = "moments"
    __table_args__ = (
        CheckConstraint(f"source IN ({enum_values(ReconstructionSource)})", name="source"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    stop_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("stops.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MomentMedia(Base, GeneratedRecordMixin):
    __tablename__ = "moment_media"
    __table_args__ = (
        CheckConstraint(f"source IN ({enum_values(ReconstructionSource)})", name="source"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence"
        ),
        UniqueConstraint("moment_id", "media_item_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    moment_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("moments.id", ondelete="CASCADE"), nullable=False
    )
    media_item_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("media_items.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class MomentParticipant(Base, GeneratedRecordMixin):
    __tablename__ = "moment_participants"
    __table_args__ = (
        CheckConstraint(f"source IN ({enum_values(ReconstructionSource)})", name="source"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence"
        ),
        UniqueConstraint("moment_id", "trip_member_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    moment_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("moments.id", ondelete="CASCADE"), nullable=False
    )
    trip_member_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("trip_members.id", ondelete="RESTRICT"),
        nullable=False,
    )


class TripLeg(Base, GeneratedRecordMixin):
    __tablename__ = "trip_legs"
    __table_args__ = (
        CheckConstraint(f"source IN ({enum_values(ReconstructionSource)})", name="source"),
        CheckConstraint(f"route_source IN ({enum_values(RouteSource)})", name="route_source"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence"
        ),
        UniqueConstraint("from_stop_id", "to_stop_id", "reconstruction_run_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    trip_day_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trip_days.id", ondelete="CASCADE"), nullable=False
    )
    from_stop_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("stops.id", ondelete="CASCADE"), nullable=False
    )
    to_stop_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("stops.id", ondelete="CASCADE"), nullable=False
    )
    route_source: Mapped[str] = mapped_column(String(40), nullable=False)
    geometry: Mapped[object | None] = mapped_column(GeographyLineString)


class ReviewItem(Base, GeneratedRecordMixin):
    __tablename__ = "review_items"
    __table_args__ = (
        CheckConstraint(f"source IN ({enum_values(ReconstructionSource)})", name="source"),
        CheckConstraint(f"item_type IN ({enum_values(ReviewItemType)})", name="item_type"),
        CheckConstraint(f"severity IN ({enum_values(ReviewSeverity)})", name="severity"),
        CheckConstraint(f"status IN ({enum_values(ReviewItemStatus)})", name="status"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    media_item_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("media_items.id", ondelete="SET NULL")
    )
    item_type: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'medium'")
    )
    target_type: Mapped[str | None] = mapped_column(String(80))
    target_id: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True))
    target_refs: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default=text("'open'"))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EditOperation(Base, TimestampMixin):
    __tablename__ = "edit_operations"
    __table_args__ = (
        CheckConstraint(
            f"operation_type IN ({enum_values(EditOperationType)})", name="operation_type"
        ),
        CheckConstraint(f"status IN ({enum_values(EditOperationStatus)})", name="status"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    operation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'applied'")
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_member_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trip_members.id", ondelete="SET NULL")
    )
    review_item_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("review_items.id", ondelete="SET NULL")
    )
    target_type: Mapped[str | None] = mapped_column(String(80))
    target_id: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True))
    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    before_values: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    after_values: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    undo_of_operation_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("edit_operations.id", ondelete="SET NULL")
    )


class StoryVersion(Base, TimestampMixin):
    __tablename__ = "story_versions"
    __table_args__ = (
        CheckConstraint(f"state IN ({enum_values(StoryVersionState)})", name="state"),
        CheckConstraint("version_number > 0", name="version_number_positive"),
        UniqueConstraint("trip_id", "version_number"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False, server_default=text("'pending'"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    manifest_store_alias: Mapped[str | None] = mapped_column(String(100))
    manifest_object_key: Mapped[str | None] = mapped_column(Text)
    manifest_checksum: Mapped[str | None] = mapped_column(Text)
    manifest_byte_size: Mapped[int | None] = mapped_column(BigInteger)
    asset_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    source_reconstruction_run_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("reconstruction_runs.id", ondelete="SET NULL")
    )
    created_by_member_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trip_members.id", ondelete="SET NULL")
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    publication_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    audit: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class StoryDraftProjection(Base, TimestampMixin):
    __tablename__ = "story_draft_projections"
    __table_args__ = (UniqueConstraint("trip_id"),)

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    source_reconstruction_run_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("reconstruction_runs.id", ondelete="CASCADE")
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


class StoryDayPhotoProjection(Base, TimestampMixin):
    __tablename__ = "story_day_photo_projections"
    __table_args__ = (UniqueConstraint("trip_id", "trip_day_id"),)

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    trip_day_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trip_days.id", ondelete="CASCADE"), nullable=False
    )
    source_reconstruction_run_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("reconstruction_runs.id", ondelete="CASCADE")
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


class StoryStopPhotoProjection(Base, TimestampMixin):
    __tablename__ = "story_stop_photo_projections"
    __table_args__ = (UniqueConstraint("trip_id", "stop_id"),)

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    trip_day_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trip_days.id", ondelete="CASCADE"), nullable=False
    )
    stop_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("stops.id", ondelete="CASCADE"), nullable=False
    )
    source_reconstruction_run_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("reconstruction_runs.id", ondelete="CASCADE")
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


class AssetDownloadGrant(Base, TimestampMixin):
    __tablename__ = "asset_download_grants"
    __table_args__ = (UniqueConstraint("asset_id"),)

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    asset_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("media_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_type: Mapped[str] = mapped_column(String(40), nullable=False)
    download_url: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ShareLink(Base, TimestampMixin):
    __tablename__ = "share_links"
    __table_args__ = (
        CheckConstraint(f"status IN ({enum_values(ShareLinkStatus)})", name="status"),
        UniqueConstraint("token_hash"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    story_version_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("story_versions.id", ondelete="SET NULL")
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default=text("'active'"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
Index("ix_capture_devices_trip_id", CaptureDevice.trip_id)
Index("ix_capture_devices_member_id", CaptureDevice.contributor_member_id)
Index("ix_media_items_trip_id", MediaItem.trip_id)
Index("ix_media_items_contributor_member_id", MediaItem.contributor_member_id)
Index("ix_media_items_capture_device_id", MediaItem.capture_device_id)
Index("ix_media_items_effective_captured_at_utc", MediaItem.effective_captured_at_utc)
Index("ix_media_items_sha256", MediaItem.sha256)
Index("ix_media_items_perceptual_hash", MediaItem.perceptual_hash)
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
Index("ix_similarity_groups_trip_id", SimilarityGroup.trip_id)
Index("ix_similarity_groups_representative", SimilarityGroup.representative_media_item_id)
Index("ix_similarity_group_members_media", SimilarityGroupMember.media_item_id)
Index(
    "ix_clock_offset_suggestions_trip_status",
    DeviceClockOffsetSuggestion.trip_id,
    DeviceClockOffsetSuggestion.status,
)
Index(
    "ix_clock_offset_suggestions_device",
    DeviceClockOffsetSuggestion.capture_device_id,
)
Index("ix_reconstruction_runs_trip_id", ReconstructionRun.trip_id)
Index("ix_trip_days_trip_id", TripDay.trip_id)
Index("ix_places_trip_id", Place.trip_id)
Index("ix_places_centroid_gist", Place.centroid, postgresql_using="gist")
Index("ix_stops_trip_day_id", Stop.trip_day_id)
Index("ix_stops_trip_id", Stop.trip_id)
Index("ix_stops_centroid_gist", Stop.centroid, postgresql_using="gist")
Index("ix_moments_stop_id", Moment.stop_id)
Index("ix_moments_trip_id", Moment.trip_id)
Index("ix_moment_media_media_item_id", MomentMedia.media_item_id)
Index("ix_moment_participants_trip_member_id", MomentParticipant.trip_member_id)
Index("ix_trip_legs_trip_day_id", TripLeg.trip_day_id)
Index("ix_trip_legs_geometry_gist", TripLeg.geometry, postgresql_using="gist")
Index("ix_review_items_trip_id", ReviewItem.trip_id)
Index("ix_review_items_media_item_id", ReviewItem.media_item_id)
Index("ix_review_items_trip_status", ReviewItem.trip_id, ReviewItem.status)
Index("ix_edit_operations_trip_created", EditOperation.trip_id, EditOperation.created_at)
Index("ix_edit_operations_review_item_id", EditOperation.review_item_id)
Index("ix_story_versions_trip_version", StoryVersion.trip_id, StoryVersion.version_number)
Index("ix_story_versions_trip_state", StoryVersion.trip_id, StoryVersion.state)
Index(
    "ix_story_draft_projections_trip_run",
    StoryDraftProjection.trip_id,
    StoryDraftProjection.source_reconstruction_run_id,
)
Index(
    "ix_story_day_photo_projections_trip_run",
    StoryDayPhotoProjection.trip_id,
    StoryDayPhotoProjection.source_reconstruction_run_id,
)
Index(
    "ix_story_stop_photo_projections_trip_run",
    StoryStopPhotoProjection.trip_id,
    StoryStopPhotoProjection.source_reconstruction_run_id,
)
Index("ix_asset_download_grants_expires_at", AssetDownloadGrant.expires_at)
Index("ix_share_links_trip_id", ShareLink.trip_id)
Index("ix_share_links_story_version_id", ShareLink.story_version_id)
