from __future__ import annotations

import logging
from collections.abc import Mapping

from tripweave.ports.metrics import MetricDimensions, MetricEvent, MetricsRecorder, MetricValue

logger = logging.getLogger("tripweave.metrics")


def _string_dimensions(dimensions: MetricDimensions) -> dict[str, str]:
    return {key: str(value) for key, value in dimensions.items() if value is not None}


class StructuredLogMetricsRecorder:
    def record(self, event: MetricEvent) -> None:
        logger.info(
            "metric",
            extra={
                "service": "api",
                "event": "metric",
                "metric_name": event.name,
                "metric_value": event.value,
                "metric_unit": event.unit,
                "metric_dimensions": _string_dimensions(event.dimensions),
            },
        )

    def duration(
        self,
        name: str,
        milliseconds: MetricValue,
        dimensions: Mapping[str, str | int | float | bool | None] | None = None,
    ) -> None:
        self.record(
            MetricEvent(
                name=name,
                value=milliseconds,
                unit="ms",
                dimensions=dimensions or {},
            )
        )

    def count(
        self,
        name: str,
        value: MetricValue = 1,
        dimensions: Mapping[str, str | int | float | bool | None] | None = None,
    ) -> None:
        self.record(
            MetricEvent(
                name=name,
                value=value,
                unit="count",
                dimensions=dimensions or {},
            )
        )


def create_metrics_recorder() -> MetricsRecorder:
    return StructuredLogMetricsRecorder()
