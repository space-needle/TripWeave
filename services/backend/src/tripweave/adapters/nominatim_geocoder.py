from __future__ import annotations

import json
import time
from collections.abc import Callable
from threading import Lock
from typing import cast
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from tripweave.ports.geocoder import GeocodeResult

DEFAULT_NOMINATIM_ENDPOINT = "https://nominatim.openstreetmap.org/reverse"
DEFAULT_USER_AGENT = "TripWeave local MVP (https://github.com/openai/tripweave)"

POI_CATEGORIES = {
    "amenity",
    "historic",
    "leisure",
    "shop",
    "tourism",
}
POI_TYPES = {
    "cafe",
    "restaurant",
    "attraction",
    "museum",
    "gallery",
    "hotel",
    "guest_house",
    "viewpoint",
    "place_of_worship",
    "monument",
    "memorial",
}
AREA_ADDRESS_KEYS = (
    "neighbourhood",
    "quarter",
    "suburb",
    "village",
    "town",
    "city_district",
    "city",
    "county",
)


class NominatimGeocoder:
    """OpenStreetMap Nominatim reverse geocoder.

    The adapter returns a POI or area name instead of a full postal address and
    degrades to an empty result when the public service is unavailable.
    """

    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_NOMINATIM_ENDPOINT,
        user_agent: str = DEFAULT_USER_AGENT,
        accept_language: str = "en",
        timeout_seconds: float = 2.0,
        min_interval_seconds: float = 1.0,
        opener: Callable[[Request, float], bytes] | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._user_agent = user_agent
        self._accept_language = accept_language
        self._timeout_seconds = timeout_seconds
        self._min_interval_seconds = min_interval_seconds
        self._last_request_at = 0.0
        self._request_lock = Lock()
        self._opener = opener or self._default_opener

    def reverse_geocode(self, *, latitude: float, longitude: float) -> GeocodeResult:
        query = urlencode(
            {
                "format": "jsonv2",
                "lat": f"{latitude:.7f}",
                "lon": f"{longitude:.7f}",
                "zoom": "18",
                "addressdetails": "1",
                "namedetails": "1",
                "accept-language": self._accept_language,
            }
        )
        request = Request(
            f"{self._endpoint}?{query}",
            headers={"User-Agent": self._user_agent, "Accept": "application/json"},
            method="GET",
        )
        try:
            payload = json.loads(self._request(request))
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
            return GeocodeResult(name=None, confidence=None, source="nominatim")
        return geocode_result_from_nominatim(payload)

    def name_for_point(self, *, latitude: float, longitude: float) -> GeocodeResult:
        return self.reverse_geocode(latitude=latitude, longitude=longitude)

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


def geocode_result_from_nominatim(payload: object) -> GeocodeResult:
    if not isinstance(payload, dict):
        return GeocodeResult(name=None, confidence=None, source="nominatim")

    name = poi_name(payload) or area_name(payload)
    if name is None:
        return GeocodeResult(name=None, confidence=None, source="nominatim")

    confidence = confidence_from_payload(payload)
    return GeocodeResult(name=name, confidence=confidence, source="nominatim")


def poi_name(payload: dict[str, object]) -> str | None:
    category = string_value(payload.get("category"))
    place_type = string_value(payload.get("type"))
    if category not in POI_CATEGORIES and place_type not in POI_TYPES:
        return None

    namedetails = payload.get("namedetails")
    if isinstance(namedetails, dict):
        for key in ("name", "name:en", "name:ko"):
            name = string_value(namedetails.get(key))
            if name:
                return name
    return string_value(payload.get("name"))


def area_name(payload: dict[str, object]) -> str | None:
    address = payload.get("address")
    if not isinstance(address, dict):
        return None
    for key in AREA_ADDRESS_KEYS:
        name = string_value(address.get(key))
        if name:
            return name
    return None


def confidence_from_payload(payload: dict[str, object]) -> float:
    raw = payload.get("importance")
    if isinstance(raw, int | float):
        return max(0.0, min(float(raw), 1.0))
    return 0.7


def string_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
