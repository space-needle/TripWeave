from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tripweave.adapters.orm import MediaItem, ProcessingJob, Trip, TripMember, User
from tripweave.application.pagination import Page, PageRequest
from tripweave.domain.enums import ProcessingJobState


def _page_query(session: Session, statement: object, page: PageRequest) -> Page[object]:
    items = tuple(session.scalars(statement.limit(page.limit).offset(page.offset)).all())  # type: ignore[attr-defined]
    total_statement = select(func.count()).select_from(statement.subquery())  # type: ignore[attr-defined]
    total = session.execute(total_statement).scalar_one()
    return Page(items=items, limit=page.limit, offset=page.offset, total=total)


class PostgresUsersRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def email_exists(self, email: str) -> bool:
        normalized = email.strip().lower()
        return (
            self._session.execute(
                select(User.id).where(User.email == normalized).limit(1)
            ).scalar_one_or_none()
            is not None
        )


class PostgresTripsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_user(self, user_id: UUID, page: PageRequest) -> Page[object]:
        statement = (
            select(Trip)
            .join(TripMember, TripMember.trip_id == Trip.id)
            .where(TripMember.user_id == user_id, TripMember.removed_at.is_(None))
            .order_by(Trip.created_at.desc(), Trip.id)
        )
        return _page_query(self._session, statement, page)


class PostgresMediaItemsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_trip(self, trip_id: UUID, page: PageRequest) -> Page[object]:
        statement = (
            select(MediaItem)
            .where(MediaItem.trip_id == trip_id, MediaItem.deleted_at.is_(None))
            .order_by(MediaItem.effective_captured_at_utc, MediaItem.created_at, MediaItem.id)
        )
        return _page_query(self._session, statement, page)


class PostgresProcessingJobsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue(
        self,
        *,
        job_type: str,
        target_type: str,
        target_id: UUID,
        idempotency_key: str,
        priority: int = 100,
        run_after: datetime | None = None,
    ) -> object:
        job = ProcessingJob(
            job_type=job_type,
            target_type=target_type,
            target_id=target_id,
            idempotency_key=idempotency_key,
            priority=priority,
        )
        if run_after is not None:
            job.run_after = run_after
        self._session.add(job)
        return job

    def list_by_state(
        self, states: Sequence[ProcessingJobState], page: PageRequest
    ) -> Page[object]:
        statement = (
            select(ProcessingJob)
            .where(ProcessingJob.state.in_([state.value for state in states]))
            .order_by(ProcessingJob.priority, ProcessingJob.run_after, ProcessingJob.created_at)
        )
        return _page_query(self._session, statement, page)
