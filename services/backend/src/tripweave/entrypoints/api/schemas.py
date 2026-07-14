from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tripweave.application.auth import normalize_email
from tripweave.domain.enums import MediaVisibility, TripStatus, TripVisibility


class UserResponse(BaseModel):
    id: UUID
    email: str
    display_name: str


class AuthResponse(BaseModel):
    user: UserResponse
    csrf_token: str = Field(alias="csrfToken")


class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(alias="displayName", min_length=1, max_length=160)

    @field_validator("email")
    @classmethod
    def normalize(cls, value: str) -> str:
        normalized = normalize_email(value)
        if "@" not in normalized or "." not in normalized.rsplit("@", 1)[-1]:
            raise ValueError("Enter a valid email address")
        return normalized


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize(cls, value: str) -> str:
        return normalize_email(value)


class MeResponse(BaseModel):
    user: UserResponse


class GuestMemberResponse(BaseModel):
    id: UUID
    trip_id: UUID = Field(alias="tripId")
    display_name: str = Field(alias="displayName")
    role: str
    csrf_token: str = Field(alias="csrfToken")


class TripCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    start_date: date | None = Field(default=None, alias="startDate")
    end_date: date | None = Field(default=None, alias="endDate")
    timezone_id: str = Field(default="UTC", alias="timezoneId", min_length=1, max_length=100)
    day_cutoff_hour: int = Field(default=4, alias="dayCutoffHour", ge=0, le=23)

    @field_validator("timezone_id")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezoneId must be an IANA time zone like Asia/Seoul") from exc
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> TripCreateRequest:
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("endDate must be on or after startDate")
        return self


class TripUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    start_date: date | None = Field(default=None, alias="startDate")
    end_date: date | None = Field(default=None, alias="endDate")
    timezone_id: str | None = Field(default=None, alias="timezoneId", min_length=1, max_length=100)
    day_cutoff_hour: int | None = Field(default=None, alias="dayCutoffHour", ge=0, le=23)
    status: str | None = Field(default=None)
    visibility: str | None = Field(default=None)

    @field_validator("timezone_id")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezoneId must be an IANA time zone like Asia/Seoul") from exc
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is not None and value not in {item.value for item in TripStatus}:
            raise ValueError("Invalid trip status")
        return value

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, value: str | None) -> str | None:
        if value is not None and value not in {item.value for item in TripVisibility}:
            raise ValueError("Invalid trip visibility")
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> TripUpdateRequest:
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("endDate must be on or after startDate")
        return self


class TripResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None
    start_date: date | None = Field(alias="startDate")
    end_date: date | None = Field(alias="endDate")
    timezone_id: str = Field(alias="timezoneId")
    day_cutoff_hour: int = Field(alias="dayCutoffHour")
    status: str
    visibility: str
    role: str
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class TripsListResponse(BaseModel):
    trips: list[TripResponse]


class InvitationCreateRequest(BaseModel):
    expires_in_seconds: int | None = Field(
        default=None, alias="expiresInSeconds", ge=60, le=60 * 60 * 24 * 30
    )


class InvitationResponse(BaseModel):
    id: UUID
    trip_id: UUID = Field(alias="tripId")
    role: str
    status: str
    expires_at: datetime = Field(alias="expiresAt")
    use_count: int = Field(alias="useCount")
    max_uses: int = Field(alias="maxUses")
    revoked_at: datetime | None = Field(default=None, alias="revokedAt")
    accepted_at: datetime | None = Field(default=None, alias="acceptedAt")
    invite_url: str | None = Field(default=None, alias="inviteUrl")


class InvitationsListResponse(BaseModel):
    invitations: list[InvitationResponse]


class InvitationPreviewResponse(BaseModel):
    trip_id: UUID = Field(alias="tripId")
    title: str
    role: str
    expires_at: datetime = Field(alias="expiresAt")
    status: str


class InvitationAcceptRequest(BaseModel):
    display_name: str = Field(alias="displayName", min_length=1, max_length=160)


class MemberResponse(BaseModel):
    id: UUID
    display_name: str = Field(alias="displayName")
    role: str
    joined_at: datetime = Field(alias="joinedAt")
    removed_at: datetime | None = Field(default=None, alias="removedAt")
    is_guest: bool = Field(alias="isGuest")


class MemberRosterResponse(BaseModel):
    members: list[MemberResponse]


class UploadFileRegisterRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=500)
    byte_size: int = Field(alias="byteSize", gt=0)
    mime_type: str = Field(alias="mimeType", min_length=1, max_length=255)


class UploadSessionCreateRequest(BaseModel):
    files: list[UploadFileRegisterRequest] = Field(min_length=1)


class BlobRefResponse(BaseModel):
    store_alias: str = Field(alias="storeAlias")
    object_key: str = Field(alias="objectKey")
    checksum_algorithm: str | None = Field(default=None, alias="checksumAlgorithm")
    checksum: str | None = None
    size_bytes: int | None = Field(default=None, alias="sizeBytes")
    content_type: str | None = Field(default=None, alias="contentType")


class UploadGrantResponse(BaseModel):
    blob_ref: BlobRefResponse = Field(alias="blobRef")
    method: str
    url: str
    headers: dict[str, str]
    expires_at: datetime = Field(alias="expiresAt")
    max_size_bytes: int = Field(alias="maxSizeBytes")
    content_type: str | None = Field(default=None, alias="contentType")


class UploadFileResponse(BaseModel):
    id: UUID
    state: str
    filename: str | None
    byte_size: int | None = Field(alias="byteSize")
    mime_type: str | None = Field(alias="mimeType")
    store_alias: str = Field(alias="storeAlias")
    object_key: str = Field(alias="objectKey")
    sha256: str | None
    media_item_id: UUID | None = Field(default=None, alias="mediaItemId")
    error_message: str | None = Field(default=None, alias="errorMessage")
    grant: UploadGrantResponse | None = None


class UploadSessionResponse(BaseModel):
    id: UUID
    trip_id: UUID = Field(alias="tripId")
    state: str
    declared_file_count: int | None = Field(alias="declaredFileCount")
    declared_total_bytes: int | None = Field(alias="declaredTotalBytes")
    files: list[UploadFileResponse]
    limits: dict[str, object]


class UploadSessionsListResponse(BaseModel):
    upload_sessions: list[UploadSessionResponse] = Field(alias="uploadSessions")


class CompleteUploadFileResponse(BaseModel):
    file: UploadFileResponse


class MediaAssetResponse(BaseModel):
    id: UUID
    asset_type: str = Field(alias="assetType")
    width: int | None
    height: int | None
    mime_type: str = Field(alias="mimeType")
    download_url: str | None = Field(default=None, alias="downloadUrl")


class MediaItemResponse(BaseModel):
    id: UUID
    filename: str | None
    processing_state: str = Field(alias="processingState")
    error_message: str | None = Field(default=None, alias="errorMessage")
    captured_at: datetime | None = Field(default=None, alias="capturedAt")
    gps_present: bool = Field(alias="gpsPresent")
    width: int | None = None
    height: int | None = None
    contributor: str
    contributor_member_id: UUID = Field(alias="contributorMemberId")
    thumbnail: MediaAssetResponse | None = None


class MediaListResponse(BaseModel):
    media: list[MediaItemResponse]


class MediaUpdateRequest(BaseModel):
    visibility: str | None = None
    include_in_story: bool | None = Field(default=None, alias="includeInStory")
    deleted: bool | None = None

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, value: str | None) -> str | None:
        if value is not None and value not in {item.value for item in MediaVisibility}:
            raise ValueError("Invalid media visibility")
        return value


class ReconstructionRunResponse(BaseModel):
    id: UUID
    state: str
    algorithm_version: str = Field(alias="algorithmVersion")
    summary: dict[str, object]
    started_at: datetime = Field(alias="startedAt")
    finished_at: datetime | None = Field(default=None, alias="finishedAt")


class ReconstructionMomentResponse(BaseModel):
    id: UUID
    position: int
    title: str | None = None
    starts_at: datetime = Field(alias="startsAt")
    ends_at: datetime = Field(alias="endsAt")
    starts_at_local: datetime | None = Field(default=None, alias="startsAtLocal")
    ends_at_local: datetime | None = Field(default=None, alias="endsAtLocal")
    media_count: int = Field(alias="mediaCount")
    contributor_count: int = Field(alias="contributorCount")


class ReconstructionStopResponse(BaseModel):
    id: UUID
    position: int
    title: str | None = None
    starts_at: datetime = Field(alias="startsAt")
    ends_at: datetime = Field(alias="endsAt")
    starts_at_local: datetime | None = Field(default=None, alias="startsAtLocal")
    ends_at_local: datetime | None = Field(default=None, alias="endsAtLocal")
    place_name: str | None = Field(default=None, alias="placeName")
    media_count: int = Field(alias="mediaCount")
    contributor_count: int = Field(alias="contributorCount")
    moments: list[ReconstructionMomentResponse]


class ReconstructionDayResponse(BaseModel):
    id: UUID
    date: date
    position: int
    title: str | None = None
    stops: list[ReconstructionStopResponse]


class ReviewItemResponse(BaseModel):
    id: UUID
    item_type: str = Field(alias="itemType")
    severity: str
    confidence: float | None = None
    target_type: str | None = Field(default=None, alias="targetType")
    target_id: UUID | None = Field(default=None, alias="targetId")
    target_refs: dict[str, object] = Field(alias="targetRefs")
    payload: dict[str, object]
    status: str
    message: str
    media_item_id: UUID | None = Field(default=None, alias="mediaItemId")
    resolution: str | None = None
    resolved_by: UUID | None = Field(default=None, alias="resolvedBy")
    resolved_at: datetime | None = Field(default=None, alias="resolvedAt")


class ReconstructionResponse(BaseModel):
    latest_run: ReconstructionRunResponse | None = Field(default=None, alias="latestRun")
    days: list[ReconstructionDayResponse]
    review_items: list[ReviewItemResponse] = Field(alias="reviewItems")


class EditOperationRequest(BaseModel):
    operation_type: str = Field(alias="operationType")
    payload: dict[str, object] = Field(default_factory=dict)
    review_item_id: UUID | None = Field(default=None, alias="reviewItemId")
    expected_updated_at: datetime | None = Field(default=None, alias="expectedUpdatedAt")


class EditOperationResponse(BaseModel):
    id: UUID
    operation_type: str = Field(alias="operationType")
    status: str
    target_type: str | None = Field(default=None, alias="targetType")
    target_id: UUID | None = Field(default=None, alias="targetId")
    before_values: dict[str, object] = Field(alias="beforeValues")
    after_values: dict[str, object] = Field(alias="afterValues")
    created_at: datetime = Field(alias="createdAt")
