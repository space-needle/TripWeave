from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any
from uuid import UUID

from sqlalchemy import literal_column, or_, select
from sqlalchemy.orm import Session

from tripweave.adapters import orm
from tripweave.adapters.local_blob_store import BlobNotFoundError
from tripweave.domain.enums import (
    MediaAssetType,
    MediaVisibility,
    ProcessingState,
    StoryVersionState,
)
from tripweave.domain.storage import BlobRef

PUBLICATION_ALGORITHM_VERSION = "publication.v1"
STORY_STORE_ALIAS = "story_published"
PRIVATE_STORE_ALIAS = "media_private"


class PublicationError(Exception):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


def publish_story_version(
    db: Session,
    *,
    blob_store: Any,
    story_version_id: UUID,
) -> None:
    story_version = db.get(orm.StoryVersion, story_version_id)
    if story_version is None:
        raise PublicationError("publication_not_found", "Publication was not found")
    if story_version.state == StoryVersionState.PUBLISHED.value:
        return
    trip = db.get(orm.Trip, story_version.trip_id)
    if trip is None:
        raise PublicationError("trip_not_found", "Trip was not found")

    now = datetime.now(UTC)
    story_version.state = StoryVersionState.PUBLISHING.value
    story_version.publication_started_at = story_version.publication_started_at or now
    story_version.updated_at = now
    db.commit()

    try:
        manifest, audit = build_manifest(db, trip=trip, story_version=story_version)
        copy_publication_assets(blob_store, manifest)
        public_manifest = strip_internal_asset_refs(manifest)
        encoded = json.dumps(public_manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        manifest_key = f"{story_version.asset_prefix}/manifest.json"
        metadata = blob_store.put(
            BlobRef(store_alias=STORY_STORE_ALIAS, object_key=manifest_key),
            BytesIO(encoded),
            max_size_bytes=max(len(encoded), 1),
            content_type="application/json",
        )
    except PublicationError as exc:
        mark_failed(db, story_version, code=exc.code, safe_message=exc.safe_message)
        raise
    except Exception as exc:
        mark_failed(db, story_version, code="publication_failed", safe_message="Publication failed")
        raise PublicationError("publication_failed", "Publication failed") from exc

    now = datetime.now(UTC)
    story_version.manifest_store_alias = STORY_STORE_ALIAS
    story_version.manifest_object_key = manifest_key
    story_version.manifest_checksum = metadata.checksum
    story_version.manifest_byte_size = metadata.size_bytes
    story_version.state = StoryVersionState.PUBLISHED.value
    story_version.published_at = now
    story_version.failed_at = None
    story_version.error_code = None
    story_version.error_message = None
    story_version.audit = audit
    story_version.updated_at = now

    share_link = db.execute(
        select(orm.ShareLink).where(
            orm.ShareLink.story_version_id == story_version.id,
            orm.ShareLink.revoked_at.is_(None),
            orm.ShareLink.status == "active",
        )
    ).scalar_one_or_none()
    if share_link is not None:
        share_link.story_version_id = story_version.id
        share_link.updated_at = now
    trip.visibility = "published"
    trip.updated_at = now
    db.commit()


def mark_failed(
    db: Session, story_version: orm.StoryVersion, *, code: str, safe_message: str
) -> None:
    now = datetime.now(UTC)
    story_version.state = StoryVersionState.FAILED.value
    story_version.failed_at = now
    story_version.updated_at = now
    story_version.error_code = code
    story_version.error_message = safe_message
    db.commit()


def build_manifest(
    db: Session,
    *,
    trip: orm.Trip,
    story_version: orm.StoryVersion,
) -> tuple[dict[str, object], dict[str, object]]:
    run = latest_reconstruction_run(db, trip.id)
    if run is None:
        raise PublicationError("not_publishable", "Run reconstruction before publishing")

    publishable_media_ids = publishable_media_ids_for_trip(db, trip.id)
    if not publishable_media_ids:
        raise PublicationError("not_publishable", "No story-visible media is ready to publish")

    asset_map = publication_asset_map(db, publishable_media_ids, story_version)
    missing = [
        str(media_id)
        for media_id in publishable_media_ids
        if not {
            MediaAssetType.THUMBNAIL.value,
            MediaAssetType.DISPLAY.value,
        }.issubset(set(asset_map.get(media_id, {})))
    ]
    if missing:
        raise PublicationError("not_publishable", "Publishable media is missing derivatives")

    stop_lat: Any = literal_column("ST_Y(stops.centroid::geometry)").label("latitude")
    stop_lon: Any = literal_column("ST_X(stops.centroid::geometry)").label("longitude")
    media_lat: Any = literal_column("ST_Y(media_items.effective_location::geometry)").label(
        "latitude"
    )
    media_lon: Any = literal_column("ST_X(media_items.effective_location::geometry)").label(
        "longitude"
    )
    leg_geometry: Any = literal_column("ST_AsGeoJSON(trip_legs.geometry::geometry)").label(
        "geometry"
    )

    days = list(
        db.scalars(
            select(orm.TripDay)
            .where(
                orm.TripDay.trip_id == trip.id,
                or_(
                    orm.TripDay.reconstruction_run_id == run.id,
                    orm.TripDay.user_locked.is_(True),
                ),
            )
            .order_by(orm.TripDay.position)
        )
    )
    stops = db.execute(
        select(orm.Stop, orm.Place, stop_lat, stop_lon)
        .join(orm.Place, orm.Place.id == orm.Stop.place_id)
        .where(
            orm.Stop.trip_id == trip.id,
            or_(orm.Stop.reconstruction_run_id == run.id, orm.Stop.user_locked.is_(True)),
        )
        .order_by(orm.Stop.position)
    ).all()
    moments = list(
        db.scalars(
            select(orm.Moment)
            .where(
                orm.Moment.trip_id == trip.id,
                or_(
                    orm.Moment.reconstruction_run_id == run.id,
                    orm.Moment.user_locked.is_(True),
                ),
            )
            .order_by(orm.Moment.position)
        )
    )
    moment_media_rows = db.execute(
        select(
            orm.MomentMedia.moment_id,
            orm.Moment.stop_id,
            orm.MediaItem,
            orm.TripMember,
            media_lat,
            media_lon,
        )
        .join(orm.Moment, orm.Moment.id == orm.MomentMedia.moment_id)
        .join(orm.MediaItem, orm.MediaItem.id == orm.MomentMedia.media_item_id)
        .join(orm.TripMember, orm.TripMember.id == orm.MediaItem.contributor_member_id)
        .where(
            orm.MomentMedia.trip_id == trip.id,
            orm.MediaItem.id.in_(publishable_media_ids),
            or_(
                orm.MomentMedia.reconstruction_run_id == run.id,
                orm.MomentMedia.user_locked.is_(True),
            ),
        )
        .order_by(orm.MediaItem.effective_captured_at_utc, orm.MediaItem.created_at)
    ).all()
    leg_rows = db.execute(
        select(orm.TripLeg, leg_geometry)
        .where(
            orm.TripLeg.trip_id == trip.id,
            or_(orm.TripLeg.reconstruction_run_id == run.id, orm.TripLeg.user_locked.is_(True)),
        )
        .order_by(orm.TripLeg.created_at, orm.TripLeg.id)
    ).all()

    participants: dict[str, dict[str, object]] = {}
    contributors_by_stop: dict[UUID, set[str]] = {}
    contributors_by_moment: dict[UUID, set[str]] = {}
    media_by_moment: dict[UUID, list[dict[str, object]]] = {}
    local_times_by_stop: dict[UUID, list[datetime]] = {}
    local_times_by_moment: dict[UUID, list[datetime]] = {}

    for moment_id, stop_id, media, contributor, latitude, longitude in moment_media_rows:
        member_key = str(contributor.id)
        participants[member_key] = {
            "id": member_key,
            "displayName": contributor.display_name,
        }
        contributors_by_stop.setdefault(stop_id, set()).add(member_key)
        contributors_by_moment.setdefault(moment_id, set()).add(member_key)
        local_capture = media_local_capture(media)
        if local_capture is not None:
            local_times_by_stop.setdefault(stop_id, []).append(local_capture)
            local_times_by_moment.setdefault(moment_id, []).append(local_capture)
        media_assets = asset_map[media.id]
        media_by_moment.setdefault(moment_id, []).append(
            {
                "id": str(media.id),
                "caption": media.caption,
                "capturedAt": iso(
                    media.effective_captured_at_utc or media.original_captured_at_utc
                ),
                "capturedAtLocal": iso(local_capture),
                "latitude": float(latitude) if latitude is not None else None,
                "longitude": float(longitude) if longitude is not None else None,
                "contributorMemberId": member_key,
                "contributor": contributor.display_name,
                "thumbnailAssetId": media_assets[MediaAssetType.THUMBNAIL.value]["id"],
                "previewAssetId": media_assets[MediaAssetType.DISPLAY.value]["id"],
            }
        )

    moments_by_stop: dict[UUID, list[dict[str, object]]] = {}
    for moment in moments:
        media_items = media_by_moment.get(moment.id, [])
        if not media_items:
            continue
        local_times = local_times_by_moment.get(moment.id, [])
        moments_by_stop.setdefault(moment.stop_id, []).append(
            {
                "id": str(moment.id),
                "position": moment.position,
                "title": moment.title,
                "startsAt": iso(moment.starts_at_utc),
                "endsAt": iso(moment.ends_at_utc),
                "startsAtLocal": iso(min(local_times) if local_times else None),
                "endsAtLocal": iso(max(local_times) if local_times else None),
                "mediaCount": len(media_items),
                "contributorCount": len(contributors_by_moment.get(moment.id, set())),
                "media": media_items,
            }
        )

    stops_by_day: dict[UUID, list[dict[str, object]]] = {}
    for stop, place, latitude, longitude in stops:
        moment_items = moments_by_stop.get(stop.id, [])
        if not moment_items:
            continue
        local_times = local_times_by_stop.get(stop.id, [])
        media_count = sum(
            int(moment["mediaCount"])
            for moment in moment_items
            if isinstance(moment["mediaCount"], int)
        )
        stops_by_day.setdefault(stop.trip_day_id, []).append(
            {
                "id": str(stop.id),
                "position": stop.position,
                "title": stop.title,
                "startsAt": iso(stop.starts_at_utc),
                "endsAt": iso(stop.ends_at_utc),
                "startsAtLocal": iso(min(local_times) if local_times else None),
                "endsAtLocal": iso(max(local_times) if local_times else None),
                "placeName": place.name,
                "latitude": float(latitude) if latitude is not None else None,
                "longitude": float(longitude) if longitude is not None else None,
                "mediaCount": media_count,
                "contributorCount": len(contributors_by_stop.get(stop.id, set())),
                "moments": moment_items,
            }
        )

    legs_by_day: dict[UUID, list[dict[str, object]]] = {}
    for leg, geometry_json in leg_rows:
        geometry = json.loads(geometry_json) if isinstance(geometry_json, str) else None
        legs_by_day.setdefault(leg.trip_day_id, []).append(
            {
                "id": str(leg.id),
                "fromStopId": str(leg.from_stop_id),
                "toStopId": str(leg.to_stop_id),
                "routeSource": leg.route_source,
                "geometry": geometry,
            }
        )

    manifest_days = [
        {
            "id": str(day.id),
            "date": day.day_date.isoformat(),
            "position": day.position,
            "title": day.title,
            "stops": stops_by_day.get(day.id, []),
            "legs": legs_by_day.get(day.id, []),
        }
        for day in days
        if stops_by_day.get(day.id)
    ]
    if not manifest_days:
        raise PublicationError("not_publishable", "No story-visible media is in the reconstruction")
    assets = [asset for by_type in asset_map.values() for asset in by_type.values()]
    manifest = {
        "schemaVersion": 1,
        "algorithmVersion": PUBLICATION_ALGORITHM_VERSION,
        "storyVersionId": str(story_version.id),
        "versionNumber": story_version.version_number,
        "publishedAt": iso(datetime.now(UTC)),
        "trip": {
            "id": str(trip.id),
            "title": trip.title,
            "description": trip.description,
            "timezoneId": trip.timezone_id,
            "dayCutoffHour": trip.day_cutoff_hour,
        },
        "participants": sorted(participants.values(), key=lambda item: str(item["displayName"])),
        "assets": assets,
        "days": manifest_days,
    }
    audit = {
        "sourceReconstructionRunId": str(run.id),
        "includedMediaCount": len(publishable_media_ids),
        "assetCount": len(assets),
        "privacy": {
            "originalsPublished": False,
            "rawExifPublished": False,
            "onlyMetadataStrippedDerivatives": True,
        },
    }
    return manifest, audit


def latest_reconstruction_run(db: Session, trip_id: UUID) -> orm.ReconstructionRun | None:
    return db.execute(
        select(orm.ReconstructionRun)
        .where(orm.ReconstructionRun.trip_id == trip_id, orm.ReconstructionRun.state == "succeeded")
        .order_by(orm.ReconstructionRun.created_at.desc(), orm.ReconstructionRun.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def publishable_media_ids_for_trip(db: Session, trip_id: UUID) -> list[UUID]:
    return list(
        db.scalars(
            select(orm.MediaItem.id)
            .where(
                orm.MediaItem.trip_id == trip_id,
                orm.MediaItem.processing_state == ProcessingState.READY.value,
                orm.MediaItem.deleted_at.is_(None),
                orm.MediaItem.include_in_story.is_(True),
                orm.MediaItem.visibility == MediaVisibility.STORY.value,
            )
            .order_by(orm.MediaItem.effective_captured_at_utc, orm.MediaItem.created_at)
        )
    )


def publication_asset_map(
    db: Session,
    media_ids: list[UUID],
    story_version: orm.StoryVersion,
) -> dict[UUID, dict[str, dict[str, object]]]:
    rows = db.execute(
        select(orm.MediaAsset)
        .where(
            orm.MediaAsset.media_item_id.in_(media_ids),
            orm.MediaAsset.asset_type.in_(
                [MediaAssetType.THUMBNAIL.value, MediaAssetType.DISPLAY.value]
            ),
            orm.MediaAsset.metadata_stripped.is_(True),
        )
        .order_by(orm.MediaAsset.media_item_id, orm.MediaAsset.asset_type)
    ).scalars()
    assets: dict[UUID, dict[str, dict[str, object]]] = {}
    for asset in rows:
        public_key = (
            f"{story_version.asset_prefix}/assets/{asset.media_item_id}/{asset.asset_type}.webp"
        )
        assets.setdefault(asset.media_item_id, {})[asset.asset_type] = {
            "id": str(asset.id),
            "sourceAssetId": str(asset.id),
            "assetType": asset.asset_type,
            "mediaItemId": str(asset.media_item_id),
            "blobRef": {
                "storeAlias": STORY_STORE_ALIAS,
                "objectKey": public_key,
                "checksumAlgorithm": "sha256",
                "checksum": asset.checksum,
                "sizeBytes": asset.byte_size,
                "contentType": asset.mime_type,
            },
            "sourceBlobRef": {
                "storeAlias": asset.store_alias,
                "objectKey": asset.object_key,
                "checksumAlgorithm": "sha256",
                "checksum": asset.checksum,
                "sizeBytes": asset.byte_size,
                "contentType": asset.mime_type,
            },
            "width": asset.width,
            "height": asset.height,
            "mimeType": asset.mime_type,
            "metadataStripped": asset.metadata_stripped,
        }
    return assets


def copy_publication_assets(blob_store: Any, manifest: dict[str, object]) -> None:
    assets = manifest.get("assets")
    if not isinstance(assets, list):
        raise PublicationError("publication_invalid", "Publication manifest is invalid")
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        source_ref = blob_ref_from_manifest(asset.get("sourceBlobRef"))
        public_ref = blob_ref_from_manifest(asset.get("blobRef"))
        if (
            source_ref.store_alias != PRIVATE_STORE_ALIAS
            or public_ref.store_alias != STORY_STORE_ALIAS
        ):
            raise PublicationError("publication_invalid", "Publication asset store is invalid")
        if blob_store.exists(public_ref):
            continue
        blob_size = asset.get("blobRef")
        max_size = 50_000_000
        if isinstance(blob_size, dict) and isinstance(blob_size.get("sizeBytes"), int):
            max_size = max(int(blob_size["sizeBytes"]), 1)
        try:
            with blob_store.open_reader(source_ref) as reader:
                blob_store.put(
                    public_ref,
                    reader,
                    max_size_bytes=max_size,
                    content_type=str(asset.get("mimeType") or "application/octet-stream"),
                )
        except BlobNotFoundError as exc:
            raise PublicationError("asset_missing", "A publication asset is missing") from exc


def strip_internal_asset_refs(manifest: dict[str, object]) -> dict[str, object]:
    sanitized = json.loads(json.dumps(manifest))
    assets = sanitized.get("assets")
    if isinstance(assets, list):
        for asset in assets:
            if isinstance(asset, dict):
                asset.pop("sourceBlobRef", None)
    return dict(sanitized)


def blob_ref_from_manifest(value: object) -> BlobRef:
    if not isinstance(value, dict):
        raise PublicationError("publication_invalid", "Publication asset is invalid")
    store_alias = value.get("storeAlias")
    object_key = value.get("objectKey")
    if not isinstance(store_alias, str) or not isinstance(object_key, str):
        raise PublicationError("publication_invalid", "Publication asset is invalid")
    return BlobRef(store_alias=store_alias, object_key=object_key)


def load_manifest(blob_store: Any, story_version: orm.StoryVersion) -> dict[str, object]:
    if not story_version.manifest_store_alias or not story_version.manifest_object_key:
        raise PublicationError("publication_unavailable", "Story is not available yet")
    blob_ref = BlobRef(
        store_alias=story_version.manifest_store_alias,
        object_key=story_version.manifest_object_key,
    )
    try:
        with blob_store.open_reader(blob_ref) as reader:
            return dict(json.loads(reader.read().decode("utf-8")))
    except BlobNotFoundError as exc:
        raise PublicationError("publication_unavailable", "Story is not available") from exc


def media_local_capture(media_item: orm.MediaItem) -> datetime | None:
    if media_item.original_captured_at_local is not None:
        return media_item.original_captured_at_local
    captured_at_utc = media_item.effective_captured_at_utc or media_item.original_captured_at_utc
    if captured_at_utc is None or media_item.original_utc_offset_minutes is None:
        return None
    return (captured_at_utc + timedelta(minutes=media_item.original_utc_offset_minutes)).replace(
        tzinfo=None
    )


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
