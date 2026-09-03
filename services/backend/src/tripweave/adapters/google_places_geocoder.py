from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from threading import Lock
from typing import cast
from urllib.request import Request, urlopen

from tripweave.ports.geocoder import GeocodeResult

DEFAULT_GOOGLE_PLACES_NEARBY_ENDPOINT = "https://places.googleapis.com/v1/places:searchNearby"
GOOGLE_PLACES_FIELD_MASK = "places.displayName,places.location,places.primaryType"


class GooglePlacesNearbyGeocoder:
    """Google Places API Nearby Search adapter for concise stop names.

    The adapter searches around a derived stop centroid and returns the closest
    named POI. It deliberately requests only a display name, location, and
    primary type so no unneeded place metadata enters the product.
    """

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str = DEFAULT_GOOGLE_PLACES_NEARBY_ENDPOINT,
        language_code: str = "en",
        radius_meters: float = 100.0,
        max_result_count: int = 10,
        timeout_seconds: float = 2.0,
        min_interval_seconds: float = 0.0,
        opener: Callable[[Request, float], bytes] | None = None,
    ) -> None:
        self._api_key = api_key
        self._endpoint = endpoint
        self._language_code = language_code
        self._radius_meters = radius_meters
        self._max_result_count = max_result_count
        self._timeout_seconds = timeout_seconds
        self._min_interval_seconds = min_interval_seconds
        self._last_request_at = 0.0
        self._request_lock = Lock()
        self._opener = opener or self._default_opener

    def reverse_geocode(
        self, *, latitude: float, longitude: float, language_code: str | None = None
    ) -> GeocodeResult:
        body = {
            "languageCode": language_code or self._language_code,
            "maxResultCount": self._max_result_count,
            "rankPreference": "DISTANCE",
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": latitude, "longitude": longitude},
                    "radius": self._radius_meters,
                }
            },
        }
        request = Request(
            self._endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Goog-Api-Key": self._api_key,
                "X-Goog-FieldMask": GOOGLE_PLACES_FIELD_MASK,
            },
            method="POST",
        )
        try:
            payload = json.loads(self._request(request))
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
            return empty_google_places_result()
        return geocode_result_from_google_places(
            payload,
            latitude=latitude,
            longitude=longitude,
            radius_meters=self._radius_meters,
        )

    def name_for_point(
        self, *, latitude: float, longitude: float, language_code: str | None = None
    ) -> GeocodeResult:
        return self.reverse_geocode(
            latitude=latitude, longitude=longitude, language_code=language_code
        )

    def _throttle(self) -> None:
        now = time.monotonic()
        wait_seconds = self._min_interval_seconds - (now - self._last_request_at)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        self._last_request_at = time.monotonic()

    def _request(self, request: Request) -> bytes:
        with self._request_lock:
            self._throttle()
            return self._opener(request, self._timeout_seconds)

    @staticmethod
    def _default_opener(request: Request, timeout_seconds: float) -> bytes:
        with urlopen(request, timeout=timeout_seconds) as response:
            return cast(bytes, response.read())


def geocode_result_from_google_places(
    payload: object,
    *,
    latitude: float,
    longitude: float,
    radius_meters: float,
) -> GeocodeResult:
    if not isinstance(payload, dict):
        return empty_google_places_result()
    places = payload.get("places")
    if not isinstance(places, list):
        return empty_google_places_result()

    candidates: list[tuple[float, str]] = []
    for place in places:
        if not isinstance(place, dict):
            continue
        name = display_name(place)
        location = place_location(place)
        if name is None or location is None:
            continue
        distance = distance_meters(latitude, longitude, *location)
        if distance <= radius_meters:
            candidates.append((distance, name))
    if not candidates:
        return empty_google_places_result()

    distance, name = min(candidates, key=lambda candidate: candidate[0])
    confidence = max(0.5, min(0.95, 0.95 * (1 - distance / (radius_meters * 2))))
    return GeocodeResult(name=name, confidence=confidence, source="google_places_nearby")


def empty_google_places_result() -> GeocodeResult:
    return GeocodeResult(name=None, confidence=None, source="google_places_nearby")


def display_name(place: dict[str, object]) -> str | None:
    display_name = place.get("displayName")
    if not isinstance(display_name, dict):
        return None
    text = display_name.get("text")
    if not isinstance(text, str):
        return None
    return text.strip() or None


def place_location(place: dict[str, object]) -> tuple[float, float] | None:
    location = place.get("location")
    if not isinstance(location, dict):
        return None
    latitude = location.get("latitude")
    longitude = location.get("longitude")
    if not isinstance(latitude, int | float) or not isinstance(longitude, int | float):
        return None
    return float(latitude), float(longitude)


def distance_meters(
    latitude: float,
    longitude: float,
    candidate_latitude: float,
    candidate_longitude: float,
) -> float:
    earth_radius_meters = 6_371_000.0
    latitude_delta = math.radians(candidate_latitude - latitude)
    longitude_delta = math.radians(candidate_longitude - longitude)
    latitude_one = math.radians(latitude)
    latitude_two = math.radians(candidate_latitude)
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(latitude_one) * math.cos(latitude_two) * math.sin(longitude_delta / 2) ** 2
    )
    return 2 * earth_radius_meters * math.asin(math.sqrt(haversine))
