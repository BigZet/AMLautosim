"""Prescribed observable contexts for synthetic rounds; never mutate live defaults."""

from copy import deepcopy
from datetime import datetime, timedelta


def context_variant(config, variant):
    result = deepcopy(config)
    behavior = result["behavior"]
    start = datetime.fromisoformat(behavior["timeline"]["starts_at"])
    if variant in (5, 7):
        offset = timedelta(hours=14)
        start += offset
        behavior["timeline"]["starts_at"] = start.isoformat()
        for event in behavior["history"]["operations"] or []:
            event["occurred_at"] = (
                datetime.fromisoformat(event["occurred_at"]) + offset
            ).isoformat()
    if variant == 0:
        behavior["history"]["operations"] = None
    elif variant == 1:
        behavior["history"]["operations"] = []
    elif variant in (2, 3, 5, 6, 7):
        amount = 2000 if variant in (2, 6) else 65000
        recipient = "A" if variant in (2, 3, 6) else "B"
        for index in range(4):
            behavior["history"]["operations"].append(
                dict(
                    id=f"review-payment-{index}",
                    occurred_at=(start - timedelta(days=index + 2)).isoformat(),
                    operation_code="card_transfer",
                    amount=f"{amount}.00",
                    counterparty_id=recipient,
                    category=None,
                )
            )
    behavior["profile"]["description"] = (
        "Учебный клиент. Сведения о прошлых операциях доступны только в показанной предыстории; "
        "неизвестная история не означает отсутствие доходов или активности."
    )
    return result


def enrich_review(package, record, valid):
    """Independent parameter schedule, never select a candidate by its score."""
    references = []
    for index, row in enumerate(package["references"]):
        variant = index % 8
        config = context_variant(package["config"], variant)
        steps = deepcopy(row["steps"])
        for i, step in enumerate(steps):
            step["interval_minutes"] = None if i == 0 else 1
        desired = (1, 10, 60, 1, 10, 60, 1440, 1)[variant]
        if desired != 1:
            for i in range(1, len(steps)):
                trial = deepcopy(steps)
                trial[i]["interval_minutes"] = desired
                if valid(trial, config):
                    steps = trial
                    break
        if variant in (3, 5, 7):
            for i, step in enumerate(steps):
                if step["card"]["code"] == "card_transfer":
                    trial = deepcopy(steps)
                    trial[i]["context"]["channel"] = "web" if variant == 3 else "branch"
                    if valid(trial, config):
                        steps = trial
                    break
        for step in steps:
            if step["card"]["code"] == "salary":
                step["action_details"]["income_basis"] = (
                    "payroll_registry",
                    "service_contract",
                    "no_reference",
                )[variant % 3]
        if variant in (5, 6, 7):
            from uuid import UUID

            desired_count = 2 if variant == 6 else 3
            purchase = next((s for s in steps if s["card"]["code"] == "purchase"), None)
            while (
                purchase
                and sum(s["card"]["code"] == "purchase" for s in steps) < desired_count
            ):
                extra = deepcopy(purchase)
                extra["amount"] = "2000"
                extra["step_id"] = str(UUID(int=200 + len(steps)))
                extra["interval_minutes"] = 1
                for position in range(1, len(steps) + 1):
                    trial = steps[:position] + [extra] + steps[position:]
                    if valid(trial, config):
                        steps = trial
                        break
                else:
                    break
        references.append(record(row["id"], steps, config, row["family"], row["group"]))
    package["references"] = references
    # Blind contexts are scheduled independently of labels; no rubric is called.
    package["challenges"] = [
        record(
            row["id"],
            row["steps"],
            context_variant(package["config"], (index * 3) % 8),
            group=row["group"],
            blind=True,
        )
        for index, row in enumerate(package["challenges"])
    ]
    return package
