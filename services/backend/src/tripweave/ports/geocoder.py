from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class GeocodeResult:
    name: str | None
    confidence: float | None
    source: str = "manual"


class Geocoder(Protocol):
    def reverse_geocode(self, *, latitude: float, longitude: float) -> GeocodeResult: ...

    def name_for_point(self, *, latitude: float, longitude: float) -> GeocodeResult: ...
