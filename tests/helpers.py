"""Step builders shared by API, integration and E2E tests."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any


def build_step(
    card: dict[str, Any],
    amount: Decimal | str | int | float,
    frequency: int = 1,
    channel: str | None = None,
    context: dict[str, Any] | None = None,
    action_details: dict[str, Any] | None = None,
    step_id: str | None = None,
) -> dict[str, Any]:
    """One request step for `card`, defaulting every declared field."""
    ctx: dict[str, Any] = {"channel": channel or card["channels"][0]}
    ctx.update(context or {})
    details = {field["key"]: field["default"] for field in card["fields"]}
    details.update(action_details or {})
    return {
        "step_id": step_id or str(uuid.uuid4()),
        "card": {"id": card["id"], "code": card["code"], "version": card["version"]},
        "amount": f"{Decimal(str(amount)):.2f}",
        "frequency": frequency,
        "context": ctx,
        "action_details": details,
    }


def put_scenario(
    client: Any,
    round_id: int,
    headers: dict[str, str],
    steps: list[dict[str, Any]],
    expected_revision: int = 0,
    mutation_id: str | None = None,
) -> Any:
    return client.put(
        f"/api/v1/rounds/{round_id}/scenario",
        json={
            "expected_revision": expected_revision,
            "client_mutation_id": mutation_id or str(uuid.uuid4()),
            "steps": steps,
        },
        headers=headers,
    )


def valid_chain(cards: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """A hard-valid reference chain that reaches the 150 000 target outflow.

    Built only from operations a default round enables, so it stays valid under
    the reduced parameter surface.
    """
    return [
        build_step(cards["salary"], 120000, 1, "bank"),
        build_step(cards["card_transfer"], 100000, 1, "mobile"),
        build_step(cards["cash_withdrawal"], 50000, 1, "atm"),
    ]


def violation_reasons(payload: dict[str, Any]) -> list[str]:
    return [item.get("reason") for item in payload.get("violations", [])]


def error_reasons(response: Any) -> list[str]:
    details = (response.json() or {}).get("details") or {}
    return [item.get("reason") for item in details.get("violations", [])]
