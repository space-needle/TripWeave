from __future__ import annotations

import json
import time
from collections.abc import Callable
from threading import Lock
from typing import cast
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from tripweave.ports.geocoder import GeocodeResult

DEFAULT_GOOGLE_GEOCODING_ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"

POI_TYPES = {
    "airport",
    "establishment",
    "natural_feature",
    "park",
    "point_of_interest",
    "premise",
}
AREA_COMPONENT_TYPES = (
    "neighborhood",
    "sublocality",
    "sublocality_level_1",
    "locality",
    "administrative_area_level_3",
    "administrative_area_level_2",
)


class GoogleGeocoder:
    """Google Maps Geocoding API reverse-geocoder.

    It chooses a POI or area component for a concise stop name rather than
    storing Google's formatted postal address. Service failures and quota
    responses degrade to an empty result so reconstruction can be retried.
    """

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str = DEFAULT_GOOGLE_GEOCODING_ENDPOINT,
        language: str = "en",
        timeout_seconds: float = 2.0,
        min_interval_seconds: float = 0.0,
        opener: Callable[[Request, float], bytes] | None = None,
    ) -> None:
        self._api_key = api_key
        self._endpoint = endpoint
        self._language = language
        self._timeout_seconds = timeout_seconds
        self._min_interval_seconds = min_interval_seconds
        self._last_request_at = 0.0
        self._request_lock = Lock()
        self._opener = opener or self._default_opener

    def reverse_geocode(self, *, latitude: float, longitude: float) -> GeocodeResult:
        query = urlencode(
            {
                "latlng": f"{latitude:.7f},{longitude:.7f}",
                "language": self._language,
                "key": self._api_key,
            }
        )
        request = Request(
            f"{self._endpoint}?{query}",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            payload = json.loads(self._request(request))
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
            return empty_google_result()
        return geocode_result_from_google(payload)

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


def empty_google_result() -> GeocodeResult:
    return GeocodeResult(name=None, confidence=None, source="google")


def geocode_result_from_google(payload: object) -> GeocodeResult:
    if not isinstance(payload, dict) or payload.get("status") != "OK":
        return empty_google_result()

    results = payload.get("results")
    if not isinstance(results, list):
        return empty_google_result()

    for result in results:
        if not isinstance(result, dict):
            continue
        name = poi_name(result)
        if name:
            return GeocodeResult(
                name=name,
                confidence=confidence_for_result(result, default=0.85),
                source="google",
            )

    for result in results:
        if not isinstance(result, dict):
            continue
        name = area_name(result)
        if name:
            return GeocodeResult(
                name=name,
                confidence=confidence_for_result(result, default=0.7),
                source="google",
            )
    return empty_google_result()


def poi_name(result: dict[str, object]) -> str | None:
    return component_name_for_types(result, POI_TYPES)


def area_name(result: dict[str, object]) -> str | None:
    for component_type in AREA_COMPONENT_TYPES:
        name = component_name_for_types(result, {component_type})
        if name:
            return name
    return None


def component_name_for_types(result: dict[str, object], target_types: set[str]) -> str | None:
    components = result.get("address_components")
    if not isinstance(components, list):
        return None
    for component in components:
        if not isinstance(component, dict):
            continue
        types = component.get("types")
        if not isinstance(types, list) or not any(item in target_types for item in types):
            continue
        name = component.get("long_name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def confidence_for_result(result: dict[str, object], *, default: float) -> float:
    return 0.5 if result.get("partial_match") is True else default
