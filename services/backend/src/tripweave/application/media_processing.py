from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from fractions import Fraction
from io import BytesIO

from PIL import ExifTags, Image, ImageFile, ImageOps, UnidentifiedImageError

try:  # HEIC is optional at runtime but installed for the local MVP image.
    from pillow_heif import register_heif_opener  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - exercised only in stripped environments.
    register_heif_opener = None

if register_heif_opener is not None:
    register_heif_opener()

ImageFile.LOAD_TRUNCATED_IMAGES = False

JPEG_SIGNATURE = b"\xff\xd8\xff"
HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}
XMP_RE = re.compile(rb"<x:xmpmeta[\s\S]{0,65536}</x:xmpmeta>")
ALGORITHM_VERSION = "media-ingest.v1"


class MediaProcessingError(Exception):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


@dataclass(frozen=True, slots=True)
class Derivative:
    asset_type: str
    content_type: str
    width: int
    height: int
    payload: bytes
    metadata_stripped: bool = True


@dataclass(frozen=True, slots=True)
class ProcessedMedia:
    detected_mime_type: str
    sha256: str
    perceptual_hash: str
    width: int
    height: int
    orientation: int | None
    captured_at_local: datetime | None
    captured_at_utc: datetime | None
    utc_offset_minutes: int | None
    latitude: float | None
    longitude: float | None
    camera_hints: dict[str, str]
    quality_signals: dict[str, object]
    raw_metadata: dict[str, object]
    derivatives: tuple[Derivative, ...]


def process_image_bytes(
    payload: bytes,
    *,
    max_pixels: int,
    max_decoded_bytes: int,
    thumbnail_max_px: int,
    preview_max_px: int,
) -> ProcessedMedia:
    detected_mime_type = detect_image_mime(payload)
    sha256 = hashlib.sha256(payload).hexdigest()
    Image.MAX_IMAGE_PIXELS = max_pixels

    try:
        with Image.open(BytesIO(payload)) as image:
            if image.format not in {"JPEG", "HEIF"}:
                raise MediaProcessingError("unsupported_image_type", "Unsupported image type")
            width, height = image.size
            enforce_pixel_limits(width, height, max_pixels, max_decoded_bytes)
            exif = image.getexif()
            metadata = extract_metadata(payload, exif, width, height)
            normalized = ImageOps.exif_transpose(image).convert("RGB")
            perceptual_hash = average_hash(normalized)
            quality_signals = estimate_quality_signals(normalized)
            raw_metadata = {
                **metadata.raw_metadata,
                "quality": quality_signals,
                "perceptual_hash_algorithm": "average_hash_8x8.v1",
            }
            derivatives = (
                make_derivative(normalized, "thumbnail", thumbnail_max_px),
                make_derivative(normalized, "display", preview_max_px),
            )
    except Image.DecompressionBombError as exc:
        raise MediaProcessingError("image_too_large", "Image dimensions are too large") from exc
    except UnidentifiedImageError as exc:
        raise MediaProcessingError("invalid_image", "File is not a supported image") from exc
    except OSError as exc:
        raise MediaProcessingError("invalid_image", "Image could not be decoded") from exc

    return ProcessedMedia(
        detected_mime_type=detected_mime_type,
        sha256=sha256,
        perceptual_hash=perceptual_hash,
        width=width,
        height=height,
        orientation=metadata.orientation,
        captured_at_local=metadata.captured_at_local,
        captured_at_utc=metadata.captured_at_utc,
        utc_offset_minutes=metadata.utc_offset_minutes,
        latitude=metadata.latitude,
        longitude=metadata.longitude,
        camera_hints=metadata.camera_hints,
        quality_signals=quality_signals,
        raw_metadata=raw_metadata,
        derivatives=derivatives,
    )


def detect_image_mime(payload: bytes) -> str:
    if payload.startswith(JPEG_SIGNATURE):
        return "image/jpeg"
    if len(payload) >= 12 and payload[4:8] == b"ftyp" and payload[8:12] in HEIF_BRANDS:
        return "image/heic"
    raise MediaProcessingError("invalid_signature", "File signature is not a supported image")


def enforce_pixel_limits(width: int, height: int, max_pixels: int, max_decoded_bytes: int) -> None:
    pixels = width * height
    if pixels <= 0 or pixels > max_pixels:
        raise MediaProcessingError("image_too_large", "Image dimensions are too large")
    if pixels * 4 > max_decoded_bytes:
        raise MediaProcessingError("image_too_large", "Image decoded size is too large")


@dataclass(frozen=True, slots=True)
class ExtractedMetadata:
    orientation: int | None
    captured_at_local: datetime | None
    captured_at_utc: datetime | None
    utc_offset_minutes: int | None
    latitude: float | None
    longitude: float | None
    camera_hints: dict[str, str]
    raw_metadata: dict[str, object]


def extract_metadata(
    payload: bytes, exif: Image.Exif, width: int, height: int
) -> ExtractedMetadata:
    named_exif: dict[str, object] = {}
    for key, value in exif.items():
        name = ExifTags.TAGS.get(key, str(key))
        if name == "GPSInfo":
            continue
        named_exif[name] = safe_value(value)

    gps_info = exif.get_ifd(ExifTags.IFD.GPSInfo) if exif else {}
    latitude, longitude = gps_to_decimal(gps_info)
    captured_at_local, captured_at_utc, utc_offset_minutes = capture_time(named_exif)
    if captured_at_utc is None:
        gps_utc = gps_time_utc(gps_info)
        if gps_utc is not None:
            captured_at_utc = gps_utc
            if captured_at_local is not None:
                utc_offset_minutes = int(
                    round((captured_at_local.replace(tzinfo=UTC) - gps_utc).total_seconds() / 60)
                )
    orientation = safe_int(named_exif.get("Orientation"))
    camera_hints = {
        key: str(named_exif[key])
        for key in ("Make", "Model", "LensModel", "Software")
        if key in named_exif and named_exif[key]
    }
    xmp = extract_xmp(payload)

    return ExtractedMetadata(
        orientation=orientation,
        captured_at_local=captured_at_local,
        captured_at_utc=captured_at_utc,
        utc_offset_minutes=utc_offset_minutes,
        latitude=latitude,
        longitude=longitude,
        camera_hints=camera_hints,
        raw_metadata={
            "algorithm_version": ALGORITHM_VERSION,
            "dimensions": {"width": width, "height": height},
            "orientation": orientation,
            "camera": camera_hints,
            "exif": named_exif,
            "gps_present": latitude is not None and longitude is not None,
            "xmp": xmp,
        },
    )


def capture_time(
    named_exif: dict[str, object],
) -> tuple[datetime | None, datetime | None, int | None]:
    raw_time = first_string(
        named_exif.get("DateTimeOriginal"),
        named_exif.get("DateTimeDigitized"),
        named_exif.get("DateTime"),
    )
    if raw_time is None:
        return None, None, None
    try:
        local = datetime.strptime(raw_time, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None, None, None

    raw_offset = first_string(
        named_exif.get("OffsetTimeOriginal"),
        named_exif.get("OffsetTimeDigitized"),
        named_exif.get("OffsetTime"),
    )
    offset_minutes = parse_offset_minutes(raw_offset)
    if offset_minutes is None:
        return local, None, None
    tz = timezone(timedelta(minutes=offset_minutes))
    utc_time = local.replace(tzinfo=tz).astimezone(UTC)
    return local, utc_time, offset_minutes


def parse_offset_minutes(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", value.strip())
    if not match:
        return None
    sign = -1 if match.group(1) == "-" else 1
    return sign * (int(match.group(2)) * 60 + int(match.group(3)))


def gps_to_decimal(gps_info: dict[int, object]) -> tuple[float | None, float | None]:
    if not gps_info:
        return None, None
    named = {ExifTags.GPSTAGS.get(key, str(key)): value for key, value in gps_info.items()}
    latitude = coordinate(named.get("GPSLatitude"), named.get("GPSLatitudeRef"))
    longitude = coordinate(named.get("GPSLongitude"), named.get("GPSLongitudeRef"))
    return latitude, longitude


def gps_time_utc(gps_info: dict[int, object]) -> datetime | None:
    if not gps_info:
        return None
    named = {ExifTags.GPSTAGS.get(key, str(key)): value for key, value in gps_info.items()}
    date_stamp = first_string(named.get("GPSDateStamp"))
    time_stamp = named.get("GPSTimeStamp")
    if date_stamp is None or not isinstance(time_stamp, (tuple, list)) or len(time_stamp) != 3:
        return None
    parts = [to_float(part) for part in time_stamp]
    if any(part is None for part in parts):
        return None
    hour, minute, second = parts
    if hour is None or minute is None or second is None:
        return None
    try:
        date_part = datetime.strptime(date_stamp, "%Y:%m:%d")
    except ValueError:
        return None
    whole_second = int(second)
    microsecond = int(round((second - whole_second) * 1_000_000))
    return datetime(
        date_part.year,
        date_part.month,
        date_part.day,
        int(hour),
        int(minute),
        whole_second,
        microsecond,
        tzinfo=UTC,
    )


def coordinate(value: object, ref: object) -> float | None:
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        return None
    parts = [to_float(part) for part in value]
    if any(part is None for part in parts):
        return None
    degrees, minutes, seconds = parts
    if degrees is None or minutes is None or seconds is None:
        return None
    decimal = degrees + minutes / 60 + seconds / 3600
    ref_text = str(ref)
    if ref_text in {"S", "W"}:
        decimal = -decimal
    return float(decimal)


def make_derivative(image: Image.Image, asset_type: str, max_px: int) -> Derivative:
    derivative = image.copy()
    derivative.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
    output = BytesIO()
    derivative.save(output, format="WEBP", quality=82, method=4, exif=b"")
    payload = output.getvalue()
    return Derivative(
        asset_type=asset_type,
        content_type="image/webp",
        width=derivative.width,
        height=derivative.height,
        payload=payload,
    )


def average_hash(image: Image.Image) -> str:
    grayscale = image.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
    values = list(grayscale.getdata())
    average = sum(values) / len(values)
    bits = "".join("1" if value >= average else "0" for value in values)
    return f"{int(bits, 2):016x}"


def estimate_quality_signals(image: Image.Image) -> dict[str, object]:
    grayscale = image.convert("L").resize((256, 256), Image.Resampling.BILINEAR)
    values = list(grayscale.getdata())
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    clipping = sum(1 for value in values if value <= 2 or value >= 253) / len(values)
    resolution = image.width * image.height
    return {
        "resolution": resolution,
        "width": image.width,
        "height": image.height,
        "sharpness": round(variance / (255 * 255), 6),
        "exposureClipping": round(clipping, 6),
        "orientation": "landscape" if image.width >= image.height else "portrait",
    }


def extract_xmp(payload: bytes) -> str | None:
    match = XMP_RE.search(payload)
    if not match:
        return None
    return sanitize_text(match.group(0).decode("utf-8", errors="replace"))


def safe_value(value: object) -> object:
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, str | int | float | bool) or value is None:
        return sanitize_text(value) if isinstance(value, str) else value
    if isinstance(value, Fraction):
        return float(value)
    if isinstance(value, tuple | list):
        return [safe_value(item) for item in value[:20]]
    return sanitize_text(str(value))[:500]


def sanitize_text(value: str) -> str:
    return "".join(
        character
        for character in value
        if character == "\n" or character == "\r" or character == "\t" or ord(character) >= 0x20
    )[:10_000]


def safe_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float | str | Fraction):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def to_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def first_string(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
