from tripweave.domain.enums import UploadState

TERMINAL_UPLOAD_STATES = frozenset(
    {
        UploadState.COMPLETED,
        UploadState.CANCELLED,
        UploadState.FAILED,
    }
)

ALLOWED_UPLOAD_TRANSITIONS: dict[UploadState, frozenset[UploadState]] = {
    UploadState.REGISTERING: frozenset(
        {UploadState.REGISTERED, UploadState.CANCELLED, UploadState.FAILED}
    ),
    UploadState.REGISTERED: frozenset(
        {UploadState.TRANSFERRING, UploadState.CANCELLED, UploadState.FAILED}
    ),
    UploadState.TRANSFERRING: frozenset(
        {UploadState.TRANSFERRED, UploadState.CANCELLED, UploadState.FAILED}
    ),
    UploadState.TRANSFERRED: frozenset(
        {UploadState.VERIFYING, UploadState.CANCELLED, UploadState.FAILED}
    ),
    UploadState.VERIFYING: frozenset(
        {UploadState.VERIFIED, UploadState.CANCELLED, UploadState.FAILED}
    ),
    UploadState.VERIFIED: frozenset(
        {UploadState.COMPLETED, UploadState.CANCELLED, UploadState.FAILED}
    ),
    UploadState.COMPLETED: frozenset(),
    UploadState.CANCELLED: frozenset(),
    UploadState.FAILED: frozenset(),
}


def can_transition_upload_state(current: UploadState, target: UploadState) -> bool:
    return target in ALLOWED_UPLOAD_TRANSITIONS[current]


def require_upload_state_transition(current: UploadState, target: UploadState) -> None:
    if not can_transition_upload_state(current, target):
        raise ValueError(f"cannot transition upload state from {current.value} to {target.value}")
