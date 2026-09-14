"""Versioned elapsed-time semantics, independent of the server clock."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

TIMELINE_VERSION = "operation-timeline-v1"
INTERVAL_COSTS = {1: 0, 10: 1, 60: 2, 1440: 4}


def canonical_intervals(steps):
    return [
        None if index == 0 else (step.get("interval_minutes") or 1)
        for index, step in enumerate(steps)
    ]


def operation_timeline(steps, timeline):
    """Elapsed minutes use UTC arithmetic, then project into the frozen zone.

    00:00–05:59 night; 06:00–17:59 day; 18:00–23:59 evening.
    First step has no pace. 1 min rapid, 10 normal, 60/1440 spaced.
    """
    if timeline.get("version", TIMELINE_VERSION) != TIMELINE_VERSION:
        raise ValueError("Неизвестная версия временной шкалы")
    start = datetime.fromisoformat(str(timeline["starts_at"]).replace("Z", "+00:00"))
    if start.tzinfo is None:
        raise ValueError("Начало сценария требует часовой пояс")
    zone = ZoneInfo(timeline["timezone"])
    elapsed = 0
    result = []
    for index, (step, interval) in enumerate(zip(steps, canonical_intervals(steps)), 1):
        if interval is not None and (
            type(interval) is not int or interval not in INTERVAL_COSTS
        ):
            raise ValueError("Недопустимый интервал")
        elapsed += interval or 0
        local = (start.astimezone(UTC) + timedelta(minutes=elapsed)).astimezone(zone)
        result.append(
            {
                "step_id": str(step["step_id"]),
                "step_index": index,
                "occurred_at": local.isoformat(),
                "elapsed_minutes": elapsed,
                "interval_minutes": interval,
                "waiting_time_cost": INTERVAL_COSTS[interval]
                if interval is not None
                else 0,
                "time_of_day": "night"
                if local.hour < 6
                else "day"
                if local.hour < 18
                else "evening",
                "pace": None
                if interval is None
                else "rapid"
                if interval == 1
                else "normal"
                if interval == 10
                else "spaced",
            }
        )
    return result
