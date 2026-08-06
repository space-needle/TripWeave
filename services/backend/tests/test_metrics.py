import logging
from typing import Any, cast

import pytest

from tripweave.adapters.metrics import StructuredLogMetricsRecorder


def test_structured_log_metrics_recorder_emits_metric_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder = StructuredLogMetricsRecorder()

    with caplog.at_level(logging.INFO, logger="tripweave.metrics"):
        recorder.duration(
            "story_projection.response.duration_ms",
            12.5,
            {"projection": "draft", "cache_hit": True, "ignored": None},
        )

    record = cast(Any, caplog.records[-1])
    assert record.message == "metric"
    assert record.service == "api"
    assert record.event == "metric"
    assert record.metric_name == "story_projection.response.duration_ms"
    assert record.metric_value == 12.5
    assert record.metric_unit == "ms"
    assert record.metric_dimensions == {
        "projection": "draft",
        "cache_hit": "True",
    }
