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
    UNKNOWN_TIME = "unknown_time"
    UNKNOWN_LOCATION = "unknown_location"
    POSSIBLE_WRONG_DAY = "possible_wrong_day"
    POSSIBLE_STOP_MERGE = "possible_stop_merge"
    POSSIBLE_STOP_SPLIT = "possible_stop_split"
    POSSIBLE_CLOCK_OFFSET = "possible_clock_offset"
    UNASSIGNED_MEDIA = "unassigned_media"
    FAILED_MEDIA_PROCESSING = "failed_media_processing"


class ReviewSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ReviewItemStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class EditOperationType(StrEnum):
    MOVE_MEDIA = "move_media"
    MOVE_AFTER_MIDNIGHT_MEDIA = "move_after_midnight_media"
    MERGE_STOPS = "merge_stops"
    SPLIT_STOP = "split_stop"
    MERGE_MOMENTS = "merge_moments"
    RENAME_DAY = "rename_day"
    RENAME_STOP = "rename_stop"
    RENAME_MOMENT = "rename_moment"
    SET_DAY_NOTE = "set_day_note"
    SET_STOP_NOTE = "set_stop_note"
    MOVE_STOP_ON_MAP = "move_stop_on_map"
    CHANGE_ROUTE_MODE = "change_route_mode"
    EXCLUDE_MEDIA_FROM_STORY = "exclude_media_from_story"
    LOCK_RECORD = "lock_record"
    RESOLVE_REVIEW_ITEM = "resolve_review_item"
    DISMISS_REVIEW_ITEM = "dismiss_review_item"
    SET_SIMILARITY_REPRESENTATIVE = "set_similarity_representative"
    ACCEPT_CLOCK_OFFSET_SUGGESTION = "accept_clock_offset_suggestion"
    REJECT_CLOCK_OFFSET_SUGGESTION = "reject_clock_offset_suggestion"


class EditOperationStatus(StrEnum):
    APPLIED = "applied"
    UNDONE = "undone"


class ProcessingJobState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SimilarityGroupType(StrEnum):
    EXACT_DUPLICATE = "exact_duplicate"
    VISUALLY_SIMILAR = "visually_similar"


class SuggestionStatus(StrEnum):
    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class StoryVersionState(StrEnum):
    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class ShareLinkStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"
