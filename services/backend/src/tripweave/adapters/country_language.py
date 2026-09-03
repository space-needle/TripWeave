from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def geocoder_language_for_point(*, db: Session, latitude: float, longitude: float) -> str:
    """Choose the place-name language from a local country-boundary lookup."""

    country_code = db.execute(
        text(
            """
            SELECT country_code
            FROM country_boundaries
            WHERE ST_Covers(
                boundary,
                ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography
            )
            LIMIT 1
            """
        ),
        {"latitude": latitude, "longitude": longitude},
    ).scalar_one_or_none()
    return geocoder_language_for_country(country_code)


def geocoder_language_for_country(country_code: str | None) -> str:
    """Prefer Korean only inside South Korea; otherwise use English."""

    return "ko" if country_code == "KR" else "en"
