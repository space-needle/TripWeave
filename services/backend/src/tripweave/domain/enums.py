from enum import StrEnum


class TripStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class TripVisibility(StrEnum):
    PRIVATE = "private"
    SHARED = "shared"
    PUBLISHED = "published"


class TripMemberRole(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    CONTRIBUTOR = "contributor"
    VIEWER = "viewer"


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"


class UploadState(StrEnum):
    REGISTERING = "registering"
    REGISTERED = "registered"
    TRANSFERRING = "transferring"
    TRANSFERRED = "transferred"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class MediaType(StrEnum):
    PHOTO = "photo"
    VIDEO = "video"
    OTHER = "other"


class TimeSource(StrEnum):
    ORIGINAL_METADATA = "original_metadata"
    USER_CORRECTION = "user_correction"
    AUTOMATION = "automation"
    UNKNOWN = "unknown"


class LocationSource(StrEnum):
    ORIGINAL_METADATA = "original_metadata"
    USER_CORRECTION = "user_correction"
    AUTOMATION = "automation"
    UNKNOWN = "unknown"


class ProcessingState(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class MediaVisibility(StrEnum):
    PRIVATE = "private"
    TRIP = "trip"
    STORY = "story"
    EXCLUDED = "excluded"


class MediaAssetType(StrEnum):
    ORIGINAL = "original"
    THUMBNAIL = "thumbnail"
    DISPLAY = "display"
    STORY = "story"


class ProcessingJobType(StrEnum):
    INGEST_MEDIA = "ingest_media"
    METADATA_EXTRACTION = "metadata_extraction"
    ALIGNMENT = "alignment"
    GROUPING = "grouping"
    DERIVATIVE_GENERATION = "derivative_generation"
    PUBLICATION = "publication"
    DELETION = "deletion"
    REPAIR = "repair"
    RECONSTRUCT_TRIP = "reconstruct_trip"


class ProcessingTargetType(StrEnum):
    UPLOAD_FILE = "upload_file"
    MEDIA_ITEM = "media_item"
    TRIP = "trip"
    STORY_PUBLICATION = "story_publication"


class ReconstructionRunState(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ReconstructionSource(StrEnum):
    AUTOMATION = "automation"
    USER_CORRECTION = "user_correction"
    MANUAL = "manual"


class RouteSource(StrEnum):
    PHOTO_INFERRED = "photo_inferred"
    MANUAL = "manual"
    DIRECTIONS_API = "directions_api"
    GPS_TRACK = "gps_track"


class ReviewItemType(StrEnum):
    UNUSABLE_TIME = "unusable_time"
    MISSING_GPS_AMBIGUOUS = "missing_gps_ambiguous"
    LOW_CONFIDENCE_STOP = "low_confidence_stop"


class ReviewItemStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ProcessingJobState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
