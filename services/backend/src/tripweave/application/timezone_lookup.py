from __future__ import annotations

from functools import lru_cache

from timezonefinder import TimezoneFinder


@lru_cache(maxsize=1)
def _timezone_finder() -> TimezoneFinder:
    return TimezoneFinder(in_memory=True)


def timezone_for_coordinates(latitude: float | None, longitude: float | None) -> str | None:
    """Return the IANA timezone containing a valid WGS84 coordinate.

    The lookup is deliberately local: uploaded media coordinates are never sent
    to a third-party geocoding service just to resolve a timezone.
    """
    if latitude is None or longitude is None:
        return None
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None
    return _timezone_finder().timezone_at(lat=latitude, lng=longitude)
