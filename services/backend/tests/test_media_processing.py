from io import BytesIO

import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from tripweave.application.media_processing import (
    MediaProcessingError,
    ProcessedMedia,
    coordinate,
    gps_time_utc,
    process_image_bytes,
    sanitize_text,
)


def jpeg_bytes(*, exif: Image.Exif | None = None, size: tuple[int, int] = (32, 24)) -> bytes:
    image = Image.new("RGB", size, "navy")
    output = BytesIO()
    if exif is None:
        image.save(output, format="JPEG")
    else:
        image.save(output, format="JPEG", exif=exif)
    return output.getvalue()


def process(payload: bytes) -> ProcessedMedia:
    return process_image_bytes(
        payload,
        max_pixels=1_000_000,
        max_decoded_bytes=32 * 1024 * 1024,
        thumbnail_max_px=16,
        preview_max_px=24,
    )


def test_jpeg_with_exif_extracts_capture_time_and_camera() -> None:
    exif = Image.Exif()
    exif[36867] = "2024:05:06 07:08:09"
    exif[36881] = "+09:00"
    exif[271] = "TripWeave Camera"
    exif[272] = "Local Model"

    result = process(jpeg_bytes(exif=exif))

    assert result.detected_mime_type == "image/jpeg"
    assert result.captured_at_local is not None
    assert result.captured_at_utc is not None
    assert result.utc_offset_minutes == 540
    assert result.camera_hints["Make"] == "TripWeave Camera"
    assert result.derivatives[0].asset_type == "thumbnail"


def test_rotated_image_normalizes_derivative_orientation() -> None:
    exif = Image.Exif()
    exif[274] = 6

    result = process(jpeg_bytes(exif=exif, size=(20, 40)))

    assert result.orientation == 6
    assert result.derivatives[0].width > result.derivatives[0].height


def test_no_exif_still_creates_derivatives() -> None:
    result = process(jpeg_bytes())

    assert result.captured_at_local is None
    assert len(result.derivatives) == 2
    assert len(result.perceptual_hash) == 16
    assert result.quality_signals["resolution"] == 32 * 24
    assert result.raw_metadata["perceptual_hash_algorithm"] == "average_hash_8x8.v1"


def test_invalid_image_renamed_as_jpeg_is_rejected() -> None:
    with pytest.raises(MediaProcessingError) as exc:
        process(b"\xff\xd8\xffnot really a jpeg")

    assert exc.value.code == "invalid_image"


def test_oversized_dimensions_are_rejected() -> None:
    with pytest.raises(MediaProcessingError) as exc:
        process_image_bytes(
            jpeg_bytes(size=(32, 32)),
            max_pixels=100,
            max_decoded_bytes=32 * 1024 * 1024,
            thumbnail_max_px=16,
            preview_max_px=24,
        )

    assert exc.value.code == "image_too_large"


def test_derivative_metadata_is_stripped() -> None:
    exif = Image.Exif()
    exif[36867] = "2024:05:06 07:08:09"

    result = process(jpeg_bytes(exif=exif))

    for derivative in result.derivatives:
        with Image.open(BytesIO(derivative.payload)) as image:
            assert image.getexif() == {}


def test_metadata_text_sanitizer_removes_nul_characters() -> None:
    assert sanitize_text("safe\u0000text\n") == "safetext\n"


def test_gps_rational_values_are_converted_to_decimal() -> None:
    assert coordinate((IFDRational(34), IFDRational(30), IFDRational(0)), "N") == 34.5
    assert coordinate((IFDRational(127), IFDRational(30), IFDRational(0)), "W") == -127.5


def test_gps_timestamp_extracts_utc_time() -> None:
    captured_at = gps_time_utc(
        {
            7: (IFDRational(10), IFDRational(44), IFDRational(24)),
            29: "2026:06:08",
        }
    )

    assert captured_at is not None
    assert captured_at.isoformat() == "2026-06-08T10:44:24+00:00"


def test_heic_decodes_where_supported() -> None:
    pytest.importorskip("pillow_heif")
    image = Image.new("RGB", (18, 12), "green")
    output = BytesIO()
    try:
        image.save(output, format="HEIF")
    except Exception as exc:  # pragma: no cover - depends on local codec build.
        pytest.skip(f"HEIC encode is unavailable: {exc}")

    result = process(output.getvalue())

    assert result.detected_mime_type == "image/heic"
    assert result.width == 18
