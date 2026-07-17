from collections.abc import Iterable
from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt

from tripweave.ports.geocoder import GeocodeResult


@dataclass(frozen=True, slots=True)
class ManualPlaceName:
    name: str
    latitude: float
    longitude: float
    radius_meters: float = 75
    confidence: float = 1.0


class ManualGeocoder:
    """Local/manual reverse geocoder.

    The default adapter remains a no-op, but tests and local fixtures can register
    provider-neutral place names without adding an external geocoding service.
    """

    def __init__(self, places: Iterable[ManualPlaceName] | None = None) -> None:
        self._places = list(places or [])

    def reverse_geocode(self, *, latitude: float, longitude: float) -> GeocodeResult:
        best: tuple[float, ManualPlaceName] | None = None
        for place in self._places:
            distance = haversine_meters(latitude, longitude, place.latitude, place.longitude)
            if distance > place.radius_meters:
                continue
            if best is None or distance < best[0]:
                best = (distance, place)
        if best is None:
            return GeocodeResult(name=None, confidence=None, source="manual")
        _, place = best
        return GeocodeResult(name=place.name, confidence=place.confidence, source="manual")

    def name_for_point(self, *, latitude: float, longitude: float) -> GeocodeResult:
        return self.reverse_geocode(latitude=latitude, longitude=longitude)


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_meters = 6_371_000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * radius_meters * asin(sqrt(a))
