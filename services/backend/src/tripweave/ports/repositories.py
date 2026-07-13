from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from tripweave.application.pagination import Page, PageRequest
from tripweave.domain.enums import ProcessingJobState


class UsersRepository(Protocol):
    def email_exists(self, email: str) -> bool: ...


class TripsRepository(Protocol):
    def list_for_user(self, user_id: UUID, page: PageRequest) -> Page[object]: ...


class MediaItemsRepository(Protocol):
    def list_for_trip(self, trip_id: UUID, page: PageRequest) -> Page[object]: ...


class ProcessingJobsRepository(Protocol):
    def enqueue(
        self,
        *,
        job_type: str,
        target_type: str,
        target_id: UUID,
        idempotency_key: str,
        priority: int = 100,
        run_after: datetime | None = None,
    ) -> object: ...

    def list_by_state(
        self, states: Sequence[ProcessingJobState], page: PageRequest
    ) -> Page[object]: ...
