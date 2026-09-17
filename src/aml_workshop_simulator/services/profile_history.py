"""Project observed history without using current steps, resources or risk."""

from datetime import timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.aml_workshop_simulator.domain.counterparty_roles import PARTY_ROLES
from src.aml_workshop_simulator.schemas.expanded_contract import ExpandedBehavior
from src.aml_workshop_simulator.schemas.history_summary import HistorySummaryOut

CREDITS = {"salary", "incoming_transfer"}


def activity(events):
    return {
        "count": len(events),
        "inflow": sum(
            (e.amount for e in events if e.operation_code in CREDITS), Decimal("0.00")
        ),
        "outflow": sum(
            (e.amount for e in events if e.operation_code not in CREDITS),
            Decimal("0.00"),
        ),
    }


def history_summary(behavior: ExpandedBehavior) -> HistorySummaryOut | None:
    if behavior.history.version is None:
        return None
    zone = ZoneInfo(behavior.timeline.timezone)
    end = behavior.timeline.starts_at.astimezone(timezone.utc)
    start = end - timedelta(days=30)
    context = getattr(behavior, "aml_context", None)
    coverage = context.history_coverage if context is not None else None
    if context is not None and context.history_start is not None:
        start, end = context.history_start, context.history_end
    events = behavior.history.operations
    known = events is not None and coverage != "unknown"
    complete = known and coverage in (None, "complete")
    ordered = sorted(events or [], key=lambda e: (e.occurred_at, e.id))
    parties = {p.id: p for p in behavior.counterparties}
    relations = []
    for party in behavior.counterparties:
        related = [e for e in ordered if e.counterparty_id == party.id]
        relations.append(
            {
                "activity": activity(related) if known and (related or complete) else None,
                "counterparty_id": party.id,
                "observation": ("observed" if related else "absent" if complete else "unknown")
                if known
                else "unknown",
                "first_at": related[0].occurred_at.astimezone(zone)
                if related
                else None,
                "last_at": related[-1].occurred_at.astimezone(zone)
                if related
                else None,
            }
        )
    return HistorySummaryOut(
        status="observed" if known else "unknown",
        coverage=coverage,
        starts_at=start.astimezone(zone),
        ends_before=end.astimezone(zone),
        timezone=behavior.timeline.timezone,
        activity=activity(ordered) if known else None,
        active_days=len({e.occurred_at.astimezone(zone).date() for e in ordered})
        if known
        else None,
        unique_counterparties=len(
            {e.counterparty_id for e in ordered if e.counterparty_id is not None}
        )
        if known
        else None,
        by_operation={
            code: activity([e for e in ordered if e.operation_code == code])
            for code in PARTY_ROLES
        }
        if known
        else None,
        counterparties=relations,
        events=[
            {
                **e.model_dump(),
                "occurred_at": e.occurred_at.astimezone(zone),
                "category": parties[e.counterparty_id].category
                if e.operation_code == "purchase"
                else None,
            }
            for e in ordered
        ]
        if known
        else None,
    )
