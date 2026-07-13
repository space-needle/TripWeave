from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class GeocodeResult:
    name: str | None
    confidence: float | None


class Geocoder(Protocol):
    def name_for_point(self, *, latitude: float, longitude: float) -> GeocodeResult: ...
