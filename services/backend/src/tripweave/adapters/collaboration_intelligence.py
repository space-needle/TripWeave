from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from math import asin, cos, fabs, radians, sin, sqrt
from statistics import median
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, delete, literal_column, select
from sqlalchemy.orm import Session

from tripweave.adapters import orm
from tripweave.domain.enums import (
    ProcessingState,
    ReconstructionSource,
    ReviewItemStatus,
    ReviewItemType,
    ReviewSeverity,
    SimilarityGroupType,
    SuggestionStatus,
)

ALGORITHM_VERSION = "reconstruction_v1"
SIMILAR_TIME_WINDOW_SECONDS = 30 * 60
SIMILAR_LOCATION_WINDOW_METERS = 150
PHASH_DISTANCE_THRESHOLD = 10
CLOCK_SUPPORT_MINIMUM = 3
CLOCK_MAX_ABSOLUTE_OFFSET_SECONDS = 12 * 60 * 60
CLOCK_MAX_DISPERSION_SECONDS = 5 * 60


@dataclass(frozen=True, slots=True)
class IntelligenceSummary:
    similarity_groups: int
    clock_suggestions: int
    review_items: int


@dataclass(frozen=True, slots=True)
class MediaSignal:
    media: orm.MediaItem
    latitude: float | None
    longitude: float | None

    @property
    def captured_at(self) -> datetime | None:
        return self.media.effective_captured_at_utc or self.media.original_captured_at_utc


def analyze_collaboration(
    *,
    db: Session,
    trip_id: UUID,
    run: orm.ReconstructionRun,
) -> IntelligenceSummary:
    delete_unlocked_intelligence(db, trip_id)
    media = load_media(db, trip_id)
    groups = create_similarity_groups(db, run, trip_id, media)
    suggestions = create_clock_offset_suggestions(db, run, trip_id, media)
    return IntelligenceSummary(
        similarity_groups=groups,
        clock_suggestions=suggestions,
        review_items=suggestions,
    )


def delete_unlocked_intelligence(db: Session, trip_id: UUID) -> None:
    db.execute(
        delete(orm.DeviceClockOffsetSuggestion).where(
            orm.DeviceClockOffsetSuggestion.trip_id == trip_id,
            orm.DeviceClockOffsetSuggestion.user_locked.is_(False),
        )
    )
    db.execute(
        delete(orm.SimilarityGroup).where(
            orm.SimilarityGroup.trip_id == trip_id,
            orm.SimilarityGroup.user_locked.is_(False),
        )
    )


def load_media(db: Session, trip_id: UUID) -> list[MediaSignal]:
    lat: ColumnElement[Any] = literal_column(
        "ST_Y(media_items.effective_location::geometry)"
    ).label("latitude")
    lon: ColumnElement[Any] = literal_column(
        "ST_X(media_items.effective_location::geometry)"
    ).label("longitude")
    rows = db.execute(
        select(orm.MediaItem, lat, lon)
        .where(
            orm.MediaItem.trip_id == trip_id,
            orm.MediaItem.deleted_at.is_(None),
            orm.MediaItem.processing_state == ProcessingState.READY.value,
        )
        .order_by(orm.MediaItem.effective_captured_at_utc, orm.MediaItem.created_at)
    ).all()
    return [
        MediaSignal(
            media=media_item,
            latitude=float(latitude) if latitude is not None else None,
            longitude=float(longitude) if longitude is not None else None,
        )
        for media_item, latitude, longitude in rows
    ]


def create_similarity_groups(
    db: Session,
    run: orm.ReconstructionRun,
    trip_id: UUID,
    media: list[MediaSignal],
) -> int:
    grouped_ids: set[UUID] = set()
    count = 0

    by_sha: dict[str, list[MediaSignal]] = defaultdict(list)
    for item in media:
        if item.media.sha256:
            by_sha[item.media.sha256].append(item)
    for items in by_sha.values():
        if len(items) < 2:
            continue
        persist_similarity_group(
            db,
            run,
            trip_id,
            items,
            group_type=SimilarityGroupType.EXACT_DUPLICATE,
            reason="Exact duplicate by SHA-256.",
            similarity_score=1.0,
            confidence=1.0,
        )
        grouped_ids.update(item.media.id for item in items)
        count += 1

    similar_sets = visually_similar_sets(
        [item for item in media if item.media.id not in grouped_ids]
    )
    for items in similar_sets:
        persist_similarity_group(
            db,
            run,
            trip_id,
            items,
            group_type=SimilarityGroupType.VISUALLY_SIMILAR,
            reason="Visually similar media within compatible time and location bounds.",
            similarity_score=0.85,
            confidence=0.82,
        )
        count += 1
    return count


def visually_similar_sets(media: list[MediaSignal]) -> list[list[MediaSignal]]:
    parent: dict[UUID, UUID] = {item.media.id: item.media.id for item in media}

    def find(media_id: UUID) -> UUID:
        while parent[media_id] != media_id:
            media_id = parent[media_id]
        return media_id

    def union(left: UUID, right: UUID) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    ordered = sorted(media, key=lambda item: item.captured_at or datetime.min.replace(tzinfo=UTC))
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            if not candidate_bounds_match(left, right):
                continue
            if left.media.perceptual_hash and right.media.perceptual_hash:
                distance = hamming_hex(left.media.perceptual_hash, right.media.perceptual_hash)
                if distance <= PHASH_DISTANCE_THRESHOLD:
                    union(left.media.id, right.media.id)

    grouped: dict[UUID, list[MediaSignal]] = defaultdict(list)
    for item in ordered:
        grouped[find(item.media.id)].append(item)
    return [items for items in grouped.values() if len(items) > 1]


def candidate_bounds_match(left: MediaSignal, right: MediaSignal) -> bool:
    if left.captured_at is not None and right.captured_at is not None:
        delta = abs((left.captured_at - right.captured_at).total_seconds())
        if delta > SIMILAR_TIME_WINDOW_SECONDS:
            return False
    return not (
        left.latitude is not None
        and left.longitude is not None
        and right.latitude is not None
        and right.longitude is not None
        and haversine_meters(left.latitude, left.longitude, right.latitude, right.longitude)
        > SIMILAR_LOCATION_WINDOW_METERS
    )


def persist_similarity_group(
    db: Session,
    run: orm.ReconstructionRun,
    trip_id: UUID,
    items: list[MediaSignal],
    *,
    group_type: SimilarityGroupType,
    reason: str,
    similarity_score: float,
    confidence: float,
) -> None:
    ranked = sorted(items, key=lambda item: technical_score(item.media), reverse=True)
    representative = ranked[0].media
    group = orm.SimilarityGroup(
        trip_id=trip_id,
        group_type=group_type.value,
        representative_media_item_id=representative.id,
        member_count=len(items),
        reason=reason,
        source=ReconstructionSource.AUTOMATION.value,
        confidence=confidence,
        algorithm_version=ALGORITHM_VERSION,
        reconstruction_run_id=run.id,
        user_locked=False,
    )
    db.add(group)
    db.flush()
    for rank, item in enumerate(ranked, start=1):
        db.add(
            orm.SimilarityGroupMember(
                similarity_group_id=group.id,
                media_item_id=item.media.id,
                rank=rank,
                similarity_score=similarity_score,
                technical_score=technical_score(item.media),
                is_representative=item.media.id == representative.id,
                signals=technical_signals(item.media),
            )
        )


def create_clock_offset_suggestions(
    db: Session,
    run: orm.ReconstructionRun,
    trip_id: UUID,
    media: list[MediaSignal],
) -> int:
    deltas_by_device: dict[UUID, list[tuple[int, UUID, UUID]]] = defaultdict(list)
    candidates = [item for item in media if item.media.capture_device_id and item.captured_at]
    for index, left in enumerate(candidates):
        for right in candidates[index + 1 :]:
            if left.media.capture_device_id == right.media.capture_device_id:
                continue
            if not strong_match_for_clock(left, right):
                continue
            assert left.captured_at is not None and right.captured_at is not None
            assert left.media.capture_device_id is not None
            assert right.media.capture_device_id is not None
            delta_left = int((right.captured_at - left.captured_at).total_seconds())
            delta_right = -delta_left
            if abs(delta_left) <= CLOCK_MAX_ABSOLUTE_OFFSET_SECONDS:
                deltas_by_device[left.media.capture_device_id].append(
                    (delta_left, left.media.id, right.media.id)
                )
                deltas_by_device[right.media.capture_device_id].append(
                    (delta_right, right.media.id, left.media.id)
                )

    count = 0
    for device_id, evidence in deltas_by_device.items():
        if len(evidence) < CLOCK_SUPPORT_MINIMUM:
            continue
        offsets = [item[0] for item in evidence]
        offset = int(round(median(offsets)))
        dispersion = int(round(median([fabs(value - offset) for value in offsets])))
        if dispersion > CLOCK_MAX_DISPERSION_SECONDS:
            continue
        confidence = min(0.95, 0.55 + len(evidence) * 0.08) * max(
            0.2, 1 - dispersion / max(CLOCK_MAX_DISPERSION_SECONDS, 1)
        )
        suggestion = orm.DeviceClockOffsetSuggestion(
            trip_id=trip_id,
            capture_device_id=device_id,
            offset_seconds=offset,
            support_count=len(evidence),
            dispersion_seconds=dispersion,
            status=SuggestionStatus.OPEN.value,
            evidence={
                "matches": [
                    {
                        "deviceMediaItemId": str(device_media_id),
                        "referenceMediaItemId": str(reference_media_id),
                        "offsetSeconds": delta,
                    }
                    for delta, device_media_id, reference_media_id in evidence[:20]
                ],
                "minimumSupport": CLOCK_SUPPORT_MINIMUM,
                "method": "median_timestamp_delta",
            },
            source=ReconstructionSource.AUTOMATION.value,
            confidence=round(confidence, 4),
            algorithm_version=ALGORITHM_VERSION,
            reconstruction_run_id=run.id,
            user_locked=False,
        )
        db.add(suggestion)
        db.flush()
        add_clock_review_item(db, run, suggestion)
        count += 1
    return count


def strong_match_for_clock(left: MediaSignal, right: MediaSignal) -> bool:
    if (
        left.latitude is not None
        and left.longitude is not None
        and right.latitude is not None
        and right.longitude is not None
        and haversine_meters(left.latitude, left.longitude, right.latitude, right.longitude)
        > SIMILAR_LOCATION_WINDOW_METERS
    ):
        return False
    if not left.media.perceptual_hash or not right.media.perceptual_hash:
        return False
    return hamming_hex(left.media.perceptual_hash, right.media.perceptual_hash) <= 8


def add_clock_review_item(
    db: Session,
    run: orm.ReconstructionRun,
    suggestion: orm.DeviceClockOffsetSuggestion,
) -> None:
    db.add(
        orm.ReviewItem(
            trip_id=suggestion.trip_id,
            item_type=ReviewItemType.POSSIBLE_CLOCK_OFFSET.value,
            severity=ReviewSeverity.MEDIUM.value,
            target_type="device_clock_offset_suggestion",
            target_id=suggestion.id,
            target_refs={"suggestionId": str(suggestion.id)},
            status=ReviewItemStatus.OPEN.value,
            message=(f"A camera clock may be offset by {suggestion.offset_seconds} seconds."),
            payload={
                "suggestionId": str(suggestion.id),
                "captureDeviceId": str(suggestion.capture_device_id),
                "offsetSeconds": suggestion.offset_seconds,
                "supportCount": suggestion.support_count,
                "dispersionSeconds": suggestion.dispersion_seconds,
                "algorithmVersion": suggestion.algorithm_version,
            },
            source=ReconstructionSource.AUTOMATION.value,
            confidence=suggestion.confidence,
            algorithm_version=ALGORITHM_VERSION,
            reconstruction_run_id=run.id,
            user_locked=False,
        )
    )


def hamming_hex(left: str, right: str) -> int:
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError:
        return 64


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_000
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    return 2 * earth_radius_m * asin(sqrt(a))


def technical_score(media: orm.MediaItem) -> float:
    signals = technical_signals(media)
    resolution = min(float_signal(signals.get("resolution"), 0.0) / 12_000_000, 1.0)
    sharpness = min(float_signal(signals.get("sharpness"), 0.0) * 8, 1.0)
    clipping = float_signal(signals.get("exposureClipping"), 1.0)
    exposure = max(0.0, 1.0 - min(clipping * 4, 1.0))
    orientation = 1.0 if signals.get("orientation") == "landscape" else 0.9
    favorite = 1.0 if bool(signals.get("contributorFavorite", False)) else 0.0
    return round(
        min(
            1.0,
            resolution * 0.3
            + sharpness * 0.3
            + exposure * 0.25
            + orientation * 0.1
            + favorite * 0.05,
        ),
        4,
    )


def technical_signals(media: orm.MediaItem) -> dict[str, object]:
    metadata = media.original_metadata_json or {}
    quality = metadata.get("quality") if isinstance(metadata, dict) else {}
    dimensions = metadata.get("dimensions") if isinstance(metadata, dict) else {}
    signals: dict[str, object] = {}
    if isinstance(quality, dict):
        signals.update(quality)
    if isinstance(dimensions, dict):
        width = dimensions.get("width")
        height = dimensions.get("height")
        if isinstance(width, int) and isinstance(height, int):
            signals.setdefault("resolution", width * height)
            signals.setdefault("width", width)
            signals.setdefault("height", height)
            signals.setdefault("orientation", "landscape" if width >= height else "portrait")
    signals.setdefault("contributorFavorite", False)
    return signals


def float_signal(value: object, fallback: float) -> float:
    if isinstance(value, bool) or value is None:
        return fallback
    if isinstance(value, int | float | str):
        try:
            return float(value)
        except ValueError:
            return fallback
    return fallback
