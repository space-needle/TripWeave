from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4


def user_row(user_id: UUID | None = None, email: str = "traveler@example.com") -> dict[str, object]:
    return {
        "id": user_id or uuid4(),
        "email": email,
        "password_hash": "hash",
        "display_name": "Traveler",
    }


def trip_row(trip_id: UUID | None = None, created_by: UUID | None = None) -> dict[str, object]:
    return {
        "id": trip_id or uuid4(),
        "title": "Summer Trip",
        "timezone_id": "America/Los_Angeles",
        "created_by": created_by or uuid4(),
    }


def member_row(
    member_id: UUID | None = None,
    trip_id: UUID | None = None,
    user_id: UUID | None = None,
) -> dict[str, object]:
    return {
        "id": member_id or uuid4(),
        "trip_id": trip_id or uuid4(),
        "user_id": user_id,
        "role": "contributor",
        "display_name": "Contributor",
    }


def invitation_row(trip_id: UUID) -> dict[str, object]:
    return {
        "id": uuid4(),
        "trip_id": trip_id,
        "email": "guest@example.com",
        "role": "contributor",
        "token_hash": f"token-{uuid4()}",
        "expires_at": datetime.now(UTC) + timedelta(days=7),
    }
