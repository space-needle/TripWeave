from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import psycopg
from PIL import Image, ImageDraw

OWNER_EMAIL = os.environ.get("TRIPWEAVE_BROWSER_DEMO_OWNER_EMAIL", "jonghee@gmail.com")
BLOB_ROOT = Path(os.environ.get("TRIPWEAVE_BLOB_DIR", "/var/lib/tripweave/blobs"))
PRIVATE_ALIAS = "media_private"
DEMO_PREFIX = "Map Demo:"


@dataclass(frozen=True)
class DemoPoint:
    filename: str
    captured_at: str | None
    latitude: float | None
    longitude: float | None
    color: tuple[int, int, int]
    label: str


@dataclass(frozen=True)
class DemoTrip:
    title: str
    description: str
    start_date: str
    end_date: str
    timezone_id: str
    points: tuple[DemoPoint, ...]


def database_url() -> str:
    value = os.environ["DATABASE_URL"]
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def image_bytes(color: tuple[int, int, int], label: str, size: tuple[int, int]) -> bytes:
    image = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(image)
    text = label[:8].upper()
    bbox = draw.textbbox((0, 0), text)
    draw.text(
        ((size[0] - (bbox[2] - bbox[0])) / 2, (size[1] - (bbox[3] - bbox[1])) / 2),
        text,
        fill=(255, 255, 255),
    )
    output = BytesIO()
    image.save(output, format="WEBP", quality=82)
    return output.getvalue()


def write_blob(object_key: str, payload: bytes) -> tuple[int, str]:
    path = BLOB_ROOT / PRIVATE_ALIAS / object_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return len(payload), hashlib.sha256(payload).hexdigest()


def parse_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def demo_trips() -> tuple[DemoTrip, ...]:
    return (
        DemoTrip(
            title=f"{DEMO_PREFIX} Korea Cities 2024",
            description="Zoom from Korea overview into city-level markers.",
            start_date="2024-04-08",
            end_date="2024-04-17",
            timezone_id="Asia/Seoul",
            points=(
                DemoPoint(
                    "seoul-palace.jpg",
                    "2024-04-08T01:00:00Z",
                    37.5796,
                    126.9770,
                    (201, 75, 62),
                    "Seoul",
                ),
                DemoPoint(
                    "seoul-han-river.jpg",
                    "2024-04-09T08:30:00Z",
                    37.5219,
                    126.9402,
                    (217, 132, 57),
                    "Han",
                ),
                DemoPoint(
                    "incheon.jpg",
                    "2024-04-10T03:00:00Z",
                    37.4563,
                    126.7052,
                    (66, 141, 185),
                    "Incheon",
                ),
                DemoPoint(
                    "gangneung.jpg",
                    "2024-04-11T04:00:00Z",
                    37.7519,
                    128.8761,
                    (42, 135, 104),
                    "Gangneung",
                ),
                DemoPoint(
                    "jeonju.jpg",
                    "2024-04-13T05:00:00Z",
                    35.8242,
                    127.1480,
                    (156, 92, 175),
                    "Jeonju",
                ),
                DemoPoint(
                    "busan.jpg", "2024-04-15T06:00:00Z", 35.1796, 129.0756, (38, 103, 162), "Busan"
                ),
                DemoPoint(
                    "jeju.jpg", "2024-04-17T02:00:00Z", 33.4996, 126.5312, (60, 154, 128), "Jeju"
                ),
            ),
        ),
        DemoTrip(
            title=f"{DEMO_PREFIX} Europe Loop 2023",
            description="Multi-country trip that separates across Europe as you zoom in.",
            start_date="2023-09-02",
            end_date="2023-09-18",
            timezone_id="Europe/Paris",
            points=(
                DemoPoint(
                    "paris.jpg", "2023-09-02T09:00:00Z", 48.8566, 2.3522, (186, 75, 89), "Paris"
                ),
                DemoPoint(
                    "amsterdam.jpg", "2023-09-05T10:00:00Z", 52.3676, 4.9041, (51, 127, 181), "AMS"
                ),
                DemoPoint(
                    "berlin.jpg", "2023-09-08T11:00:00Z", 52.5200, 13.4050, (94, 132, 65), "Berlin"
                ),
                DemoPoint(
                    "prague.jpg", "2023-09-11T09:30:00Z", 50.0755, 14.4378, (154, 101, 57), "Prague"
                ),
                DemoPoint(
                    "rome.jpg", "2023-09-16T08:00:00Z", 41.9028, 12.4964, (134, 77, 148), "Rome"
                ),
            ),
        ),
        DemoTrip(
            title=f"{DEMO_PREFIX} US West Road Trip 2022",
            description="Long-distance route for continent-level and regional clustering.",
            start_date="2022-06-01",
            end_date="2022-06-14",
            timezone_id="America/Los_Angeles",
            points=(
                DemoPoint(
                    "san-francisco.jpg",
                    "2022-06-01T17:00:00Z",
                    37.7749,
                    -122.4194,
                    (49, 118, 151),
                    "SF",
                ),
                DemoPoint(
                    "yosemite.jpg",
                    "2022-06-04T18:00:00Z",
                    37.8651,
                    -119.5383,
                    (69, 142, 89),
                    "Yosemite",
                ),
                DemoPoint(
                    "las-vegas.jpg",
                    "2022-06-08T04:00:00Z",
                    36.1699,
                    -115.1398,
                    (190, 96, 55),
                    "Vegas",
                ),
                DemoPoint(
                    "grand-canyon.jpg",
                    "2022-06-10T19:00:00Z",
                    36.1069,
                    -112.1129,
                    (176, 87, 72),
                    "Canyon",
                ),
                DemoPoint(
                    "los-angeles.jpg",
                    "2022-06-14T03:00:00Z",
                    34.0522,
                    -118.2437,
                    (80, 92, 172),
                    "LA",
                ),
            ),
        ),
        DemoTrip(
            title=f"{DEMO_PREFIX} Seoul Neighborhoods 2025",
            description="Dense city trip for high-zoom marker splitting.",
            start_date="2025-01-03",
            end_date="2025-01-06",
            timezone_id="Asia/Seoul",
            points=(
                DemoPoint(
                    "hongdae.jpg",
                    "2025-01-03T04:00:00Z",
                    37.5563,
                    126.9236,
                    (211, 83, 103),
                    "Hongdae",
                ),
                DemoPoint(
                    "jongno.jpg",
                    "2025-01-03T07:00:00Z",
                    37.5730,
                    126.9794,
                    (71, 126, 187),
                    "Jongno",
                ),
                DemoPoint(
                    "seongsu.jpg",
                    "2025-01-04T05:00:00Z",
                    37.5446,
                    127.0557,
                    (70, 154, 128),
                    "Seongsu",
                ),
                DemoPoint(
                    "gangnam.jpg",
                    "2025-01-05T06:00:00Z",
                    37.4979,
                    127.0276,
                    (160, 88, 166),
                    "Gangnam",
                ),
                DemoPoint(
                    "jamsil.jpg",
                    "2025-01-06T09:00:00Z",
                    37.5133,
                    127.1028,
                    (198, 119, 55),
                    "Jamsil",
                ),
            ),
        ),
        DemoTrip(
            title=f"{DEMO_PREFIX} Time Filter Sampler",
            description=(
                "Sparse trips across years, plus a no-location photo excluded from the map."
            ),
            start_date="2021-03-01",
            end_date="2026-02-02",
            timezone_id="UTC",
            points=(
                DemoPoint(
                    "taipei-2021.jpg",
                    "2021-03-01T06:00:00Z",
                    25.0330,
                    121.5654,
                    (64, 143, 164),
                    "2021",
                ),
                DemoPoint(
                    "sydney-2026.jpg",
                    "2026-02-02T02:00:00Z",
                    -33.8688,
                    151.2093,
                    (69, 122, 187),
                    "2026",
                ),
                DemoPoint(
                    "no-location.jpg", "2024-07-01T02:00:00Z", None, None, (120, 120, 120), "No GPS"
                ),
            ),
        ),
    )


def main() -> None:
    with psycopg.connect(database_url()) as connection, connection.cursor() as cursor:
        user_row = cursor.execute(
            "SELECT id, display_name FROM users WHERE email = %s",
            (OWNER_EMAIL,),
        ).fetchone()
        if user_row is None:
            raise RuntimeError(f"Owner user not found: {OWNER_EMAIL}")
        user_id, display_name = user_row
        old_trip_ids = [
            row[0]
            for row in cursor.execute(
                "SELECT id FROM trips WHERE created_by = %s AND title LIKE %s",
                (user_id, f"{DEMO_PREFIX}%"),
            ).fetchall()
        ]
        if old_trip_ids:
            cursor.execute("DELETE FROM trips WHERE id = ANY(%s)", (old_trip_ids,))
        shutil.rmtree(BLOB_ROOT / PRIVATE_ALIAS / "map-demo", ignore_errors=True)

        created: list[dict[str, object]] = []
        for trip in demo_trips():
            trip_id = cursor.execute(
                """
                    INSERT INTO trips (
                        title, description, start_date, end_date, timezone_id,
                        day_cutoff_hour, status, visibility, created_by
                    )
                    VALUES (%s, %s, %s, %s, %s, 4, 'active', 'private', %s)
                    RETURNING id
                    """,
                (
                    trip.title,
                    trip.description,
                    trip.start_date,
                    trip.end_date,
                    trip.timezone_id,
                    user_id,
                ),
            ).fetchone()[0]
            member_id = cursor.execute(
                """
                    INSERT INTO trip_members (trip_id, user_id, role, display_name)
                    VALUES (%s, %s, 'owner', %s)
                    RETURNING id
                    """,
                (trip_id, user_id, display_name),
            ).fetchone()[0]
            mapped_count = 0
            for point in trip.points:
                original_key = f"map-demo/{trip_id}/originals/{point.filename}"
                original_payload = image_bytes(point.color, point.label, (1200, 900))
                original_size, original_checksum = write_blob(original_key, original_payload)
                captured_at = parse_time(point.captured_at)
                media_id = cursor.execute(
                    """
                        INSERT INTO media_items (
                            trip_id, contributor_member_id, media_type, original_filename,
                            declared_mime_type, detected_mime_type, byte_size,
                            original_store_alias, original_object_key, effective_captured_at_utc,
                            original_captured_at_utc, effective_location, original_location,
                            time_source, location_source, time_confidence, location_confidence,
                            sha256, processing_state, visibility, include_in_story
                        )
                        VALUES (
                            %s, %s, 'photo', %s, 'image/jpeg', 'image/jpeg', %s,
                            %s, %s, %s, %s,
                            CASE
                                WHEN CAST(%s AS double precision) IS NULL THEN NULL
                                ELSE ST_SetSRID(
                                    ST_MakePoint(
                                        CAST(%s AS double precision),
                                        CAST(%s AS double precision)
                                    ),
                                    4326
                                )::geography
                            END,
                            CASE
                                WHEN CAST(%s AS double precision) IS NULL THEN NULL
                                ELSE ST_SetSRID(
                                    ST_MakePoint(
                                        CAST(%s AS double precision),
                                        CAST(%s AS double precision)
                                    ),
                                    4326
                                )::geography
                            END,
                            %s, %s, %s, %s, %s, 'ready', 'story', true
                        )
                        RETURNING id
                        """,
                    (
                        trip_id,
                        member_id,
                        point.filename,
                        original_size,
                        PRIVATE_ALIAS,
                        original_key,
                        captured_at,
                        captured_at,
                        point.latitude,
                        point.longitude,
                        point.latitude,
                        point.latitude,
                        point.longitude,
                        point.latitude,
                        "original_metadata" if captured_at else "unknown",
                        "original_metadata" if point.latitude is not None else "unknown",
                        1.0 if captured_at else None,
                        1.0 if point.latitude is not None else None,
                        original_checksum,
                    ),
                ).fetchone()[0]
                if point.latitude is not None:
                    mapped_count += 1
                for asset_type, size in (("thumbnail", (240, 180)), ("display", (960, 720))):
                    asset_key = f"map-demo/{trip_id}/assets/{media_id}/{asset_type}.webp"
                    asset_payload = image_bytes(point.color, point.label, size)
                    asset_size, asset_checksum = write_blob(asset_key, asset_payload)
                    cursor.execute(
                        """
                            INSERT INTO media_assets (
                                media_item_id, asset_type, store_alias, object_key, mime_type,
                                width, height, byte_size, checksum, metadata_stripped
                            )
                            VALUES (%s, %s, %s, %s, 'image/webp', %s, %s, %s, %s, true)
                            """,
                        (
                            media_id,
                            asset_type,
                            PRIVATE_ALIAS,
                            asset_key,
                            size[0],
                            size[1],
                            asset_size,
                            asset_checksum,
                        ),
                    )
            created.append({"title": trip.title, "mappedPoints": mapped_count})
        connection.commit()
    print({"ownerEmail": OWNER_EMAIL, "trips": created})


if __name__ == "__main__":
    main()
