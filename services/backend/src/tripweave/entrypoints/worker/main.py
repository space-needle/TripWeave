from __future__ import annotations

import hashlib
import logging
import random
import signal
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from time import monotonic
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from tripweave.adapters import orm
from tripweave.adapters.blob_store_factory import create_blob_store
from tripweave.adapters.database import check_database, create_database_engine
from tripweave.adapters.local_blob_store import BlobNotFoundError, LocalBlobStore
from tripweave.adapters.manual_geocoder import ManualGeocoder
from tripweave.adapters.publication import PublicationError, publish_story_version
from tripweave.adapters.reconstruction import reconstruct_trip
from tripweave.adapters.worker_heartbeat import write_heartbeat
from tripweave.application.media_processing import (
    MediaProcessingError,
    ProcessedMedia,
    process_image_bytes,
)
from tripweave.config import Settings, get_settings
from tripweave.domain.enums import (
    LocationSource,
    MediaAssetType,
    ProcessingJobState,
    ProcessingJobType,
    ProcessingState,
    ProcessingTargetType,
    TimeSource,
)
from tripweave.domain.storage import BlobRef
from tripweave.logging import configure_logging

logger = logging.getLogger(__name__)

FINAL_MEDIA_ERRORS = {
    "invalid_signature",
    "unsupported_image_type",
    "invalid_image",
    "image_too_large",
}


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    id: UUID
    job_type: str
    target_type: str
    target_id: UUID
    attempts: int
    max_attempts: int


def run_worker(settings: Settings) -> None:
    configure_logging(settings.log_level)
    engine = create_database_engine(settings)
    check_database(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    blob_store = create_blob_store(settings)
    worker_id = f"worker-{uuid.uuid4()}"

    stop_event = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    threads = [
        threading.Thread(
            target=worker_loop,
            args=(settings, session_factory, blob_store, worker_id, stop_event),
            daemon=True,
            name=f"tripweave-worker-{index}",
        )
        for index in range(settings.worker_concurrency)
    ]

    logger.info(
        "worker started",
        extra={"service": "worker", "worker_id": worker_id, "concurrency": len(threads)},
    )
    for thread in threads:
        thread.start()

    heartbeat_at = 0.0
    while not stop_event.is_set():
        now = monotonic()
        if now - heartbeat_at >= settings.worker_heartbeat_seconds:
            write_heartbeat(settings.blob_dir)
            heartbeat_at = now
        stop_event.wait(0.5)

    for thread in threads:
        thread.join(timeout=5)
    logger.info("worker stopped", extra={"service": "worker", "worker_id": worker_id})


def worker_loop(
    settings: Settings,
    session_factory: sessionmaker[Session],
    blob_store: LocalBlobStore,
    worker_id: str,
    stop_event: threading.Event,
) -> None:
    while not stop_event.is_set():
        try:
            with session_factory() as db:
                job = claim_job(db, settings, worker_id)
        except SQLAlchemyError:
            logger.exception(
                "worker database polling failed",
                extra={"service": "worker", "worker_id": worker_id},
            )
            stop_event.wait(settings.worker_poll_seconds)
            continue
        if job is None:
            stop_event.wait(settings.worker_poll_seconds)
            continue
        handle_job(settings, session_factory, blob_store, worker_id, job)


def claim_job(db: Session, settings: Settings, worker_id: str) -> ClaimedJob | None:
    now = datetime.now(UTC)
    locked_before = now - timedelta(seconds=settings.worker_lock_timeout_seconds)
    row = (
        db.execute(
            text(
                """
            WITH candidate AS (
                SELECT id
                FROM processing_jobs
                WHERE (
                    state = 'pending'
                    AND run_after <= :now
                    AND attempts < max_attempts
                ) OR (
                    state = 'running'
                    AND locked_at < :locked_before
                    AND attempts < max_attempts
                )
                ORDER BY priority ASC, run_after ASC, created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE processing_jobs
            SET
                state = 'running',
                attempts = attempts + 1,
                locked_at = :now,
                locked_by = :worker_id,
                started_at = COALESCE(started_at, :now),
                error_code = NULL,
                error_message = NULL
            WHERE id = (SELECT id FROM candidate)
            RETURNING id, job_type, target_type, target_id, attempts, max_attempts
            """
            ),
            {"now": now, "locked_before": locked_before, "worker_id": worker_id},
        )
        .mappings()
        .first()
    )
    db.commit()
    if row is None:
        return None
    return ClaimedJob(
        id=row["id"],
        job_type=str(row["job_type"]),
        target_type=str(row["target_type"]),
        target_id=row["target_id"],
        attempts=int(row["attempts"]),
        max_attempts=int(row["max_attempts"]),
    )


def handle_job(
    settings: Settings,
    session_factory: sessionmaker[Session],
    blob_store: LocalBlobStore,
    worker_id: str,
    job: ClaimedJob,
) -> None:
    logger.info(
        "processing job claimed",
        extra={"service": "worker", "worker_id": worker_id, "job_id": str(job.id)},
    )
    try:
        if (
            job.job_type == ProcessingJobType.INGEST_MEDIA.value
            and job.target_type == ProcessingTargetType.MEDIA_ITEM.value
        ):
            with session_factory() as db:
                ingest_media(db, settings, blob_store, job.target_id)
                complete_job(db, job.id)
        elif (
            job.job_type == ProcessingJobType.RECONSTRUCT_TRIP.value
            and job.target_type == ProcessingTargetType.TRIP.value
        ):
            with session_factory() as db:
                reconstruct_queued_trip(db, job.target_id)
                complete_job(db, job.id)
        elif (
            job.job_type == ProcessingJobType.PUBLICATION.value
            and job.target_type == ProcessingTargetType.STORY_PUBLICATION.value
        ):
            with session_factory() as db:
                publish_story_version(db, blob_store=blob_store, story_version_id=job.target_id)
                complete_job(db, job.id)
        else:
            raise MediaProcessingError("unknown_job_type", "Job type is not supported")
    except PublicationError as exc:
        with session_factory() as db:
            fail_job(
                db,
                job,
                error_code=exc.code,
                safe_message=exc.safe_message,
                retryable=True,
            )
    except MediaProcessingError as exc:
        with session_factory() as db:
            fail_job(
                db,
                job,
                error_code=exc.code,
                safe_message=exc.safe_message,
                retryable=exc.code not in FINAL_MEDIA_ERRORS,
            )
    except Exception:
        logger.exception(
            "processing job crashed",
            extra={"service": "worker", "worker_id": worker_id, "job_id": str(job.id)},
        )
        with session_factory() as db:
            fail_job(
                db,
                job,
                error_code="worker_error",
                safe_message="Media processing failed",
                retryable=True,
            )


def ingest_media(
    db: Session,
    settings: Settings,
    blob_store: LocalBlobStore,
    media_item_id: UUID,
) -> None:
    media_item = db.get(orm.MediaItem, media_item_id)
    if media_item is None or media_item.deleted_at is not None:
        raise MediaProcessingError("media_not_found", "Media item was not found")
    if media_item.processing_state == ProcessingState.READY.value and assets_complete(
        db, media_item.id
    ):
        return

    media_item.processing_state = ProcessingState.PROCESSING.value
    media_item.updated_at = datetime.now(UTC)
    db.commit()

    blob_ref = BlobRef(
        store_alias=media_item.original_store_alias,
        object_key=media_item.original_object_key,
    )
    try:
        with blob_store.open_reader(blob_ref) as reader:
            original_bytes = reader.read(settings.upload_max_file_bytes + 1)
    except BlobNotFoundError as exc:
        raise MediaProcessingError("original_missing", "Original file is missing") from exc
    if len(original_bytes) > settings.upload_max_file_bytes:
        raise MediaProcessingError("original_too_large", "Original file is too large")

    processed = process_image_bytes(
        original_bytes,
        max_pixels=settings.media_max_pixels,
        max_decoded_bytes=settings.media_max_decoded_bytes,
        thumbnail_max_px=settings.media_thumbnail_max_px,
        preview_max_px=settings.media_preview_max_px,
    )
    apply_processed_media(db, blob_store, media_item, processed)
    db.commit()


def reconstruct_queued_trip(db: Session, trip_id: UUID) -> None:
    trip = db.get(orm.Trip, trip_id)
    if trip is None:
        raise MediaProcessingError("trip_not_found", "Trip was not found")
    reconstruct_trip(db=db, trip=trip, geocoder=ManualGeocoder())


def apply_processed_media(
    db: Session,
    blob_store: LocalBlobStore,
    media_item: orm.MediaItem,
    processed: ProcessedMedia,
) -> None:
    now = datetime.now(UTC)
    media_item.detected_mime_type = processed.detected_mime_type
    media_item.sha256 = processed.sha256
    media_item.perceptual_hash = processed.perceptual_hash
    media_item.capture_device_id = capture_device_for_media(db, media_item, processed)
    media_item.original_captured_at_local = processed.captured_at_local
    media_item.original_captured_at_utc = processed.captured_at_utc
    media_item.original_utc_offset_minutes = processed.utc_offset_minutes
    media_item.effective_captured_at_utc = processed.captured_at_utc
    media_item.time_source = (
        TimeSource.ORIGINAL_METADATA.value
        if processed.captured_at_utc or processed.captured_at_local
        else TimeSource.UNKNOWN.value
    )
    media_item.time_confidence = 1.0 if media_item.time_source != TimeSource.UNKNOWN.value else None
    media_item.location_source = (
        LocationSource.ORIGINAL_METADATA.value
        if processed.latitude is not None and processed.longitude is not None
        else LocationSource.UNKNOWN.value
    )
    media_item.location_confidence = (
        1.0 if media_item.location_source != LocationSource.UNKNOWN.value else None
    )
    media_item.original_metadata_json = processed.raw_metadata
    media_item.processing_state = ProcessingState.READY.value
    media_item.updated_at = now

    db.flush()
    if processed.latitude is not None and processed.longitude is not None:
        db.execute(
            update(orm.MediaItem)
            .where(orm.MediaItem.id == media_item.id)
            .values(
                original_location=func.ST_SetSRID(
                    func.ST_MakePoint(processed.longitude, processed.latitude), 4326
                ),
                effective_location=func.ST_SetSRID(
                    func.ST_MakePoint(processed.longitude, processed.latitude), 4326
                ),
            )
        )

    for derivative in processed.derivatives:
        object_key = (
            f"trips/{media_item.trip_id}/media/{media_item.id}/assets/{derivative.asset_type}.webp"
        )
        metadata = blob_store.put(
            BlobRef(store_alias="media_private", object_key=object_key),
            BytesIO(derivative.payload),
            max_size_bytes=max(len(derivative.payload), 1),
            content_type=derivative.content_type,
        )
        asset = db.execute(
            select(orm.MediaAsset).where(
                orm.MediaAsset.media_item_id == media_item.id,
                orm.MediaAsset.asset_type == derivative.asset_type,
            )
        ).scalar_one_or_none()
        if asset is None:
            asset = orm.MediaAsset(
                media_item_id=media_item.id,
                asset_type=derivative.asset_type,
                store_alias="media_private",
                object_key=object_key,
                mime_type=derivative.content_type,
            )
            db.add(asset)
        asset.store_alias = "media_private"
        asset.object_key = object_key
        asset.mime_type = derivative.content_type
        asset.width = derivative.width
        asset.height = derivative.height
        asset.byte_size = metadata.size_bytes
        asset.checksum = metadata.checksum
        asset.metadata_stripped = derivative.metadata_stripped


def capture_device_for_media(
    db: Session, media_item: orm.MediaItem, processed: ProcessedMedia
) -> UUID | None:
    hints = processed.camera_hints
    make = normalized_hint(hints.get("Make"))
    model = normalized_hint(hints.get("Model"))
    software = normalized_hint(hints.get("Software"))
    if not any((make, model, software)):
        return None
    fingerprint = "|".join(
        [
            str(media_item.trip_id),
            str(media_item.contributor_member_id),
            make or "",
            model or "",
            software or "",
        ]
    )
    device_key = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:40]
    display_bits = [part for part in (make, model) if part]
    display_name = " ".join(display_bits) if display_bits else "Unknown camera"
    device = db.execute(
        select(orm.CaptureDevice).where(
            orm.CaptureDevice.trip_id == media_item.trip_id,
            orm.CaptureDevice.device_key == device_key,
        )
    ).scalar_one_or_none()
    if device is None:
        device = orm.CaptureDevice(
            trip_id=media_item.trip_id,
            contributor_member_id=media_item.contributor_member_id,
            device_key=device_key,
            make=make,
            model=model,
            software=software,
            display_name=display_name,
        )
        db.add(device)
        db.flush()
    return device.id


def normalized_hint(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = " ".join(value.split())[:160]
    return stripped or None


def assets_complete(db: Session, media_item_id: UUID) -> bool:
    asset_types = set(
        db.scalars(
            select(orm.MediaAsset.asset_type).where(orm.MediaAsset.media_item_id == media_item_id)
        ).all()
    )
    return {MediaAssetType.THUMBNAIL.value, MediaAssetType.DISPLAY.value}.issubset(asset_types)


def complete_job(db: Session, job_id: UUID) -> None:
    job = db.get(orm.ProcessingJob, job_id)
    if job is not None:
        job.state = ProcessingJobState.SUCCEEDED.value
        job.finished_at = datetime.now(UTC)
        job.locked_at = None
        job.locked_by = None
    db.commit()


def fail_job(
    db: Session,
    job: ClaimedJob,
    *,
    error_code: str,
    safe_message: str,
    retryable: bool,
) -> None:
    now = datetime.now(UTC)
    job_record = db.get(orm.ProcessingJob, job.id)
    if job_record is None:
        return

    final = not retryable or job.attempts >= job.max_attempts
    job_record.error_code = error_code
    job_record.error_message = safe_message
    job_record.locked_at = None
    job_record.locked_by = None
    if final:
        job_record.state = ProcessingJobState.FAILED.value
        job_record.finished_at = now
        if job.target_type == ProcessingTargetType.MEDIA_ITEM.value:
            mark_media_failed(db, job.target_id, safe_message)
    else:
        job_record.state = ProcessingJobState.PENDING.value
        job_record.run_after = now + backoff_delay(job.attempts)
    db.commit()


def mark_media_failed(db: Session, media_item_id: UUID, _safe_message: str) -> None:
    media_item = db.get(orm.MediaItem, media_item_id)
    if media_item is not None:
        media_item.processing_state = ProcessingState.FAILED.value
        media_item.updated_at = datetime.now(UTC)


def backoff_delay(attempts: int) -> timedelta:
    base = min(3600.0, 5.0 * (2 ** max(attempts - 1, 0)))
    jitter = random.uniform(0, min(base * 0.25, 30.0))
    return timedelta(seconds=base + jitter)


def run() -> None:
    run_worker(get_settings())


if __name__ == "__main__":
    run()
