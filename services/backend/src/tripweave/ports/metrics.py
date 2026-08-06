from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

MetricValue = int | float
MetricDimensions = Mapping[str, str | int | float | bool | None]


@dataclass(frozen=True, slots=True)
class MetricEvent:
    name: str
    value: MetricValue
    unit: str
    dimensions: MetricDimensions = field(default_factory=dict)


class MetricsRecorder(Protocol):
    def record(self, event: MetricEvent) -> None: ...

    def duration(
        self,
        name: str,
        milliseconds: MetricValue,
        dimensions: MetricDimensions | None = None,
    ) -> None: ...

    def count(
        self,
        name: str,
        value: MetricValue = 1,
        dimensions: MetricDimensions | None = None,
    ) -> None: ...
