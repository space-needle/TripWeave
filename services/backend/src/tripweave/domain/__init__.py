"""Domain package reserved for TripWeave product concepts."""

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
from tripweave.domain.storage import BlobRef
from tripweave.domain.upload_state import (
    ALLOWED_UPLOAD_TRANSITIONS,
    TERMINAL_UPLOAD_STATES,
    can_transition_upload_state,
    require_upload_state_transition,
)

__all__ = [
    "ALLOWED_UPLOAD_TRANSITIONS",
    "BlobRef",
    "InvitationStatus",
    "LocationSource",
    "MediaAssetType",
    "MediaType",
    "MediaVisibility",
    "ProcessingJobState",
    "ProcessingJobType",
    "ProcessingState",
    "ProcessingTargetType",
    "TERMINAL_UPLOAD_STATES",
    "TimeSource",
    "TripMemberRole",
    "TripStatus",
    "TripVisibility",
    "UploadState",
    "can_transition_upload_state",
    "require_upload_state_transition",
]
