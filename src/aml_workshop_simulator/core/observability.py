"""Bounded, process-local telemetry. Never accepts request bodies or SQL text."""

import asyncio
from collections import deque
from contextlib import suppress
import json
import hmac
import logging
import os
from threading import Lock
import time

import psutil

logger = logging.getLogger("aml.telemetry")


def configure_logging():
    logger.setLevel(logging.INFO)
    logger.disabled = False
    if not logger.handlers and not logging.getLogger().handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)


class Metrics:
    def __init__(self, samples=1024):
        self.samples = samples
        self.histograms = {}
        self.gauges = {}
        self.lock = Lock()
        self.process = psutil.Process()

    def observe(self, name, value):
        with self.lock:
            item = self.histograms.setdefault(
                name, {"count": 0, "sum": 0.0, "values": deque(maxlen=self.samples)}
            )
            item["count"] += 1
            item["sum"] += value
            item["values"].append(value)

    def gauge(self, name, value):
        with self.lock:
            self.gauges[name] = value

    def add(self, name, value):
        with self.lock:
            self.gauges[name] = self.gauges.get(name, 0) + value

    def snapshot(self):
        with self.lock:
            histograms = {}
            for name, item in self.histograms.items():
                values = sorted(item["values"])
                histograms[name] = {
                    "count": item["count"],
                    "sum": item["sum"],
                    "window_count": len(values),
                    "max": values[-1],
                    "p95": values[max(0, int(len(values) * 0.95 + 0.999) - 1)],
                }
            gauges = self.gauges.copy()
        cpu = self.process.cpu_times()
        return {
            "pid": os.getpid(),
            "timestamp": time.time(),
            "histograms": histograms,
            "gauges": gauges,
            "process": {
                "rss_bytes": self.process.memory_info().rss,
                "cpu_seconds": cpu.user + cpu.system,
            },
        }


metrics = Metrics()


def require_metrics(request, secret):
    from fastapi import HTTPException

    value = secret.get_secret_value() if secret else ""
    if not value or not hmac.compare_digest(
        request.headers.get("authorization", ""), "Bearer " + value
    ):
        raise HTTPException(status_code=404, detail="Not found")


def correlation_id(value):
    return (
        value
        if 0 < len(value) <= 128 and value.isascii() and value.isprintable()
        else None
    )


def request_log(request_id, client_id, route, status, duration):
    logger.info(
        json.dumps(
            {
                "event": "request",
                "request_id": request_id,
                "correlation_id": client_id,
                "route": route,
                "status": status,
                "duration_seconds": duration,
            }
        )
    )


def readiness_failure(request_id, check, exc):
    # Exception messages/SQL parameters can contain credentials. Record type only.
    logger.error(
        json.dumps(
            {
                "event": "readiness_failure",
                "request_id": request_id,
                "check": check,
                "exception_type": type(exc).__name__,
            }
        )
    )


async def sample_loop(registry=metrics, interval=1.0, gauges=None):
    while True:
        before = time.monotonic()
        await asyncio.sleep(interval)
        registry.observe(
            "event_loop_lag_seconds", max(0, time.monotonic() - before - interval)
        )
        if gauges:
            for name, value in gauges().items():
                registry.gauge(name, value)


async def stop_sampler(task):
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
