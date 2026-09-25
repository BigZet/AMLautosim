import asyncio
import json

import pytest


def test_bounded_metric_history_preserves_totals():
    from src.aml_workshop_simulator.core.observability import Metrics

    metrics = Metrics(samples=3)
    for i in range(10):
        metrics.observe("sql_seconds", i / 100)
    result = metrics.snapshot()["histograms"]["sql_seconds"]
    assert result["count"] == 10
    assert result["sum"] == pytest.approx(0.45)
    assert result["window_count"] == 3
    assert result["max"] == 0.09


def test_request_log_uses_template_and_never_request_values(caplog):
    from src.aml_workshop_simulator.core.observability import (
        request_log,
        correlation_id,
    )

    assert correlation_id("x" * 129) is None
    assert correlation_id("bad\nvalue") is None
    assert correlation_id("кириллица") is None
    with caplog.at_level("INFO", logger="aml.telemetry"):
        request_log("server-id", "client-id", "/rounds/{round_id}", 401, 0.01)
    record = json.loads(caplog.records[-1].message)
    assert record["request_id"] == "server-id"
    assert record["correlation_id"] == "client-id"
    assert record["route"] == "/rounds/{round_id}"
    assert set(record) == {
        "event",
        "request_id",
        "correlation_id",
        "route",
        "status",
        "duration_seconds",
    }


def test_loop_sampler_stops_and_exposes_process_metrics():
    from src.aml_workshop_simulator.core.observability import Metrics, sample_loop

    async def run():
        metrics = Metrics()
        task = asyncio.create_task(sample_loop(metrics, interval=0.01))
        await asyncio.sleep(0.04)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        data = metrics.snapshot()
        assert data["histograms"]["event_loop_lag_seconds"]["count"] >= 1
        assert data["process"]["rss_bytes"] > 0
        assert data["process"]["cpu_seconds"] >= 0

    asyncio.run(run())
