from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from math import asin, cos, radians, sin, sqrt
from typing import Self

ALGORITHM_VERSION = "area_visit_v1"
MIN_AREA_STOPS = 3
MAX_PREVIOUS_DISTANCE_METERS = 400.0
MAX_CENTER_DISTANCE_METERS = 700.0
MAX_AREA_DIAMETER_METERS = 1200.0
MAX_TIME_GAP_MINUTES = 45
MIN_LOCATION_CONFIDENCE = 0.5


class AreaRejectionReason(StrEnum):
    PREVIOUS_DISTANCE_EXCEEDED = "PREVIOUS_DISTANCE_EXCEEDED"
    CENTER_DISTANCE_EXCEEDED = "CENTER_DISTANCE_EXCEEDED"
    AREA_DIAMETER_EXCEEDED = "AREA_DIAMETER_EXCEEDED"
    TIME_GAP_EXCEEDED = "TIME_GAP_EXCEEDED"
    LOW_LOCATION_CONFIDENCE = "LOW_LOCATION_CONFIDENCE"
    INVALID_OR_MISSING_LOCATION = "INVALID_OR_MISSING_LOCATION"
    NON_CONTIGUOUS_STOP_ORDER = "NON_CONTIGUOUS_STOP_ORDER"


@dataclass(frozen=True, slots=True)
class AreaVisitConfig:
    min_area_stops: int = MIN_AREA_STOPS
    max_previous_distance_meters: float = MAX_PREVIOUS_DISTANCE_METERS
    max_center_distance_meters: float = MAX_CENTER_DISTANCE_METERS
    max_area_diameter_meters: float = MAX_AREA_DIAMETER_METERS
    max_time_gap_minutes: int = MAX_TIME_GAP_MINUTES
    min_location_confidence: float = MIN_LOCATION_CONFIDENCE
    algorithm_version: str = ALGORITHM_VERSION

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StopInput:
    id: str
    day_id: str
    sort_order: int
    start_time: datetime
    end_time: datetime
    latitude: float | None
    longitude: float | None
    location_confidence: float | None


@dataclass(frozen=True, slots=True)
class AreaDecisionDiagnostic:
    candidate_stop_id: str
    previous_distance_m: float | None
    center_distance_m: float | None
    farthest_member_distance_m: float | None
    new_area_diameter_m: float | None
    time_gap_seconds: int | None
    location_confidence: float | None
    accepted: bool
    rejection_reason: AreaRejectionReason | None
    algorithm_version: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["rejection_reason"] = (
            self.rejection_reason.value if self.rejection_reason is not None else None
        )
        return payload


@dataclass(frozen=True, slots=True)
class AreaVisitResult:
    area_id: str
    stop_ids: list[str]
    start_time: datetime
    end_time: datetime
    center_stop_id: str
    center_latitude: float
    center_longitude: float
    bounds: dict[str, float]
    diameter_m: float
    confidence: float
    algorithm_version: str

    def to_dict(self) -> dict[str, object]:
        return {
            "area_id": self.area_id,
            "stop_ids": self.stop_ids,
            "stop_count": len(self.stop_ids),
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "center_stop_id": self.center_stop_id,
            "center": {
                "latitude": self.center_latitude,
                "longitude": self.center_longitude,
            },
            "bounds": self.bounds,
            "diameter_m": self.diameter_m,
            "confidence": self.confidence,
            "algorithm_version": self.algorithm_version,
        }


@dataclass(frozen=True, slots=True)
class StandaloneStopResult:
    stop_id: str

    def to_dict(self) -> dict[str, object]:
        return {"stop_id": self.stop_id}


@dataclass(frozen=True, slots=True)
class AreaGroupingResult:
    areas: list[AreaVisitResult]
    standalone_stops: list[StandaloneStopResult]
    diagnostics: list[AreaDecisionDiagnostic]
    config: AreaVisitConfig

    def to_dict(self) -> dict[str, object]:
        return {
            "areas": [area.to_dict() for area in self.areas],
            "standalone_stops": [stop.to_dict() for stop in self.standalone_stops],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "summary": {
                "stop_count": sum(len(area.stop_ids) for area in self.areas)
                + len(self.standalone_stops),
                "proposed_area_count": len(self.areas),
                "standalone_stop_count": len(self.standalone_stops),
                "grouped_stop_count": sum(len(area.stop_ids) for area in self.areas),
                "stops_per_area": [len(area.stop_ids) for area in self.areas],
            },
            "config": self.config.to_dict(),
        }


@dataclass(slots=True)
class _AreaCandidate:
    stops: list[StopInput]

    @classmethod
    def from_seed(cls, seed: list[StopInput]) -> Self:
        return cls(stops=list(seed))

    def add(self, stop: StopInput) -> None:
        self.stops.append(stop)

    def finalize(self, area_index: int, config: AreaVisitConfig) -> AreaVisitResult:
        medoid = medoid_stop(self.stops)
        diameter = area_diameter_meters(self.stops)
        return AreaVisitResult(
            area_id=f"area-{area_index}",
            stop_ids=[stop.id for stop in self.stops],
            start_time=min(stop.start_time for stop in self.stops),
            end_time=max(stop.end_time for stop in self.stops),
            center_stop_id=medoid.id,
            center_latitude=medoid.latitude or 0,
            center_longitude=medoid.longitude or 0,
            bounds=bounds_for_stops(self.stops),
            diameter_m=diameter,
            confidence=confidence_for_area(self.stops, config),
            algorithm_version=config.algorithm_version,
        )


def group_area_visits(
    stops: list[StopInput],
    config: AreaVisitConfig | None = None,
) -> AreaGroupingResult:
    active_config = config or AreaVisitConfig()
    ordered_stops = sorted(
        stops,
        key=lambda stop: (stop.day_id, stop.sort_order, stop.start_time, stop.id),
    )
    areas: list[AreaVisitResult] = []
    standalone_stops: list[StandaloneStopResult] = []
    diagnostics: list[AreaDecisionDiagnostic] = []
    index = 0
    area_index = 1

    while index < len(ordered_stops):
        seed = ordered_stops[index : index + active_config.min_area_stops]
        seed_diagnostics = seed_decisions(seed, active_config)
        diagnostics.extend(seed_diagnostics)
        if (
            not seed
            or len(seed) < active_config.min_area_stops
            or not all(diagnostic.accepted for diagnostic in seed_diagnostics)
        ):
            standalone_stops.append(StandaloneStopResult(stop_id=ordered_stops[index].id))
            index += 1
            continue

        area = _AreaCandidate.from_seed(seed)
        index += active_config.min_area_stops
        while index < len(ordered_stops):
            candidate = ordered_stops[index]
            diagnostic = candidate_decision(area.stops, candidate, active_config)
            diagnostics.append(diagnostic)
            if not diagnostic.accepted:
                break
            area.add(candidate)
            index += 1

        areas.append(area.finalize(area_index, active_config))
        area_index += 1

    return AreaGroupingResult(
        areas=areas,
        standalone_stops=standalone_stops,
        diagnostics=diagnostics,
        config=active_config,
    )


def seed_decisions(
    seed: list[StopInput],
    config: AreaVisitConfig,
) -> list[AreaDecisionDiagnostic]:
    diagnostics: list[AreaDecisionDiagnostic] = []
    if len(seed) < config.min_area_stops:
        return diagnostics
    area_stops = [seed[0]]
    for candidate in seed[1:]:
        diagnostic = candidate_decision(area_stops, candidate, config)
        diagnostics.append(diagnostic)
        if not diagnostic.accepted:
            break
        area_stops.append(candidate)
    return diagnostics


def candidate_decision(
    area_stops: list[StopInput],
    candidate: StopInput,
    config: AreaVisitConfig,
) -> AreaDecisionDiagnostic:
    previous = area_stops[-1]
    if previous.day_id != candidate.day_id or candidate.sort_order != previous.sort_order + 1:
        return empty_diagnostic(
            candidate,
            config,
            AreaRejectionReason.NON_CONTIGUOUS_STOP_ORDER,
            accepted=False,
        )
    time_gap_seconds = int((candidate.start_time - previous.end_time).total_seconds())
    if time_gap_seconds > config.max_time_gap_minutes * 60:
        return empty_diagnostic(
            candidate,
            config,
            AreaRejectionReason.TIME_GAP_EXCEEDED,
            accepted=False,
            time_gap_seconds=time_gap_seconds,
        )
    if not has_location(previous) or not has_location(candidate):
        return empty_diagnostic(
            candidate,
            config,
            AreaRejectionReason.INVALID_OR_MISSING_LOCATION,
            accepted=False,
            time_gap_seconds=time_gap_seconds,
        )
    previous_distance = stop_distance_meters(previous, candidate)
    center = medoid_stop(area_stops)
    center_distance = stop_distance_meters(center, candidate)
    farthest_distance = max(stop_distance_meters(stop, candidate) for stop in area_stops)
    diameter = area_diameter_meters([*area_stops, candidate])
    reason = first_distance_rejection(
        previous_distance=previous_distance,
        center_distance=center_distance,
        diameter=diameter,
        config=config,
    )
    return AreaDecisionDiagnostic(
        candidate_stop_id=candidate.id,
        previous_distance_m=round(previous_distance, 3),
        center_distance_m=round(center_distance, 3),
        farthest_member_distance_m=round(farthest_distance, 3),
        new_area_diameter_m=round(diameter, 3),
        time_gap_seconds=time_gap_seconds,
        location_confidence=candidate.location_confidence,
        accepted=reason is None,
        rejection_reason=reason,
        algorithm_version=config.algorithm_version,
    )


def empty_diagnostic(
    candidate: StopInput,
    config: AreaVisitConfig,
    reason: AreaRejectionReason,
    *,
    accepted: bool,
    time_gap_seconds: int | None = None,
) -> AreaDecisionDiagnostic:
    return AreaDecisionDiagnostic(
        candidate_stop_id=candidate.id,
        previous_distance_m=None,
        center_distance_m=None,
        farthest_member_distance_m=None,
        new_area_diameter_m=None,
        time_gap_seconds=time_gap_seconds,
        location_confidence=candidate.location_confidence,
        accepted=accepted,
        rejection_reason=reason,
        algorithm_version=config.algorithm_version,
    )


def first_distance_rejection(
    *,
    previous_distance: float,
    center_distance: float,
    diameter: float,
    config: AreaVisitConfig,
) -> AreaRejectionReason | None:
    if previous_distance > config.max_previous_distance_meters:
        return AreaRejectionReason.PREVIOUS_DISTANCE_EXCEEDED
    if center_distance > config.max_center_distance_meters:
        return AreaRejectionReason.CENTER_DISTANCE_EXCEEDED
    if diameter > config.max_area_diameter_meters:
        return AreaRejectionReason.AREA_DIAMETER_EXCEEDED
    return None


def medoid_stop(stops: list[StopInput]) -> StopInput:
    located = [stop for stop in stops if has_location(stop)]
    if not located:
        raise ValueError("Cannot calculate medoid without located stops.")
    return min(
        located,
        key=lambda stop: (
            sum(stop_distance_meters(stop, other) for other in located if other.id != stop.id),
            stop.sort_order,
            stop.id,
        ),
    )


def area_diameter_meters(stops: list[StopInput]) -> float:
    located = [stop for stop in stops if has_location(stop)]
    if len(located) < 2:
        return 0.0
    return max(
        stop_distance_meters(first, second)
        for index, first in enumerate(located)
        for second in located[index + 1 :]
    )


def bounds_for_stops(stops: list[StopInput]) -> dict[str, float]:
    located = [stop for stop in stops if has_location(stop)]
    latitudes = [stop.latitude for stop in located if stop.latitude is not None]
    longitudes = [stop.longitude for stop in located if stop.longitude is not None]
    return {
        "min_latitude": min(latitudes),
        "min_longitude": min(longitudes),
        "max_latitude": max(latitudes),
        "max_longitude": max(longitudes),
    }


def confidence_for_area(stops: list[StopInput], config: AreaVisitConfig) -> float:
    diagnostics = seed_decisions(stops, config)
    if len(stops) > config.min_area_stops:
        area_stops = list(stops[: config.min_area_stops])
        for candidate in stops[config.min_area_stops :]:
            diagnostics.append(candidate_decision(area_stops, candidate, config))
            area_stops.append(candidate)

    confidence = 0.95
    if len(stops) == config.min_area_stops:
        confidence -= 0.05

    ratios: dict[str, float] = {}
    for diagnostic in diagnostics:
        if diagnostic.previous_distance_m is not None:
            ratios["previous_distance"] = max(
                ratios.get("previous_distance", 0),
                diagnostic.previous_distance_m / config.max_previous_distance_meters,
            )
        if diagnostic.center_distance_m is not None:
            ratios["center_distance"] = max(
                ratios.get("center_distance", 0),
                diagnostic.center_distance_m / config.max_center_distance_meters,
            )
        if diagnostic.new_area_diameter_m is not None:
            ratios["area_diameter"] = max(
                ratios.get("area_diameter", 0),
                diagnostic.new_area_diameter_m / config.max_area_diameter_meters,
            )
        if diagnostic.time_gap_seconds is not None:
            ratios["time_gap"] = max(
                ratios.get("time_gap", 0),
                diagnostic.time_gap_seconds / (config.max_time_gap_minutes * 60),
            )
    for ratio in ratios.values():
        confidence -= confidence_penalty_for_ratio(ratio)

    location_confidences = [
        stop.location_confidence for stop in stops if stop.location_confidence is not None
    ]
    if location_confidences:
        min_location_confidence = min(location_confidences)
        if min_location_confidence < 0.7:
            confidence -= 0.15
        elif min_location_confidence < 0.85:
            confidence -= 0.05

    return round(max(0.0, min(1.0, confidence)), 3)


def confidence_penalty_for_ratio(ratio: float) -> float:
    if ratio >= 0.95:
        return 0.12
    if ratio >= 0.85:
        return 0.08
    if ratio >= 0.75:
        return 0.04
    return 0.0


def has_location(stop: StopInput) -> bool:
    return stop.latitude is not None and stop.longitude is not None


def stop_distance_meters(first: StopInput, second: StopInput) -> float:
    if not has_location(first) or not has_location(second):
        raise ValueError("Cannot calculate distance for stops without locations.")
    assert first.latitude is not None
    assert first.longitude is not None
    assert second.latitude is not None
    assert second.longitude is not None
    return haversine_meters(first.latitude, first.longitude, second.latitude, second.longitude)


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_000
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    return 2 * earth_radius_m * asin(sqrt(a))
