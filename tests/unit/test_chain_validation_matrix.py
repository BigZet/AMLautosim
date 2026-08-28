from __future__ import annotations

import pytest
from src.aml_workshop_simulator.services.local_rules import ACTION_CARDS
from src.aml_workshop_simulator.services.scenario_service import (
    calculate_resource_snapshot,
)


GAME_CONFIG = {
    "resources": {
        "initial_balance": "250000.00",
        "initial_energy": 14,
        "initial_time": 18,
        "initial_trust": 100,
    },
    "objectives": {
        "target_outflow": "150000.00",
        "max_actions": 8,
    },
    "constraints": {
        "max_identical_steps": 2,
        "max_night_operations": 2,
    },
    "ruleset_version": "game-rules-v2",
}


class TestChainValidationMatrix:
    """Matrix tests covering all 8 cards, all channels, and all valid/invalid permutation constraints."""

    @pytest.mark.parametrize("card", ACTION_CARDS, ids=[c["code"] for c in ACTION_CARDS])
    def test_all_cards_valid_channels(self, card: dict) -> None:
        """Every channel listed in card['channels'] must be accepted without channel violations."""
        card_code = card["code"]
        channels = card.get("channels", ["branch"])
        for ch in channels:
            step = {
                "card_code": card_code,
                "amount": float(card["min_amount"]),
                "frequency": 1,
                "channel": ch,
                "context": {
                    "channel": ch,
                    "country_risk": "low",
                    "recipient_type": "known_counterparty",
                    "time_of_day": "day",
                    "velocity": "normal",
                    "has_documents": True,
                },
            }
            # If refund, prepend online_purchase to satisfy dependency
            steps = []
            if card_code == "refund":
                steps.append({
                    "card_code": "online_purchase",
                    "amount": 10000.0,
                    "frequency": 1,
                    "channel": "web",
                    "context": {"channel": "web"},
                })
            steps.append(step)

            res = calculate_resource_snapshot(steps, GAME_CONFIG)
            chan_violations = [v for v in res["violations"] if "недоступный канал" in v]
            assert len(chan_violations) == 0, f"Card {card_code} with channel {ch} triggered channel violation: {chan_violations}"

    def test_invalid_channel_detected(self) -> None:
        """Assigning an impossible channel to a card must be caught as a violation."""
        step = {
            "card_code": "cash_withdrawal",
            "amount": 10000.0,
            "frequency": 1,
            "channel": "exchange",  # cash withdrawal cannot be done via crypto exchange
            "context": {"channel": "exchange"},
        }
        res = calculate_resource_snapshot([step], GAME_CONFIG)
        assert any("недоступный канал" in v for v in res["violations"])

    def test_dependency_rule_refund_without_purchase(self) -> None:
        """Refund without preceding online_purchase must produce dependency violation."""
        step = {
            "card_code": "refund",
            "amount": 10000.0,
            "frequency": 1,
            "channel": "mobile",
            "context": {"channel": "mobile"},
        }
        res = calculate_resource_snapshot([step], GAME_CONFIG)
        assert any("возврат" in v.lower() or "превышает" in v.lower() for v in res["violations"])

    def test_dependency_rule_refund_with_purchase(self) -> None:
        """Refund after online_purchase must be completely valid."""
        steps = [
            {
                "card_code": "online_purchase",
                "amount": 15000.0,
                "frequency": 1,
                "channel": "web",
                "context": {"channel": "web"},
            },
            {
                "card_code": "refund",
                "amount": 5000.0,
                "frequency": 1,
                "channel": "mobile",
                "context": {"channel": "mobile"},
            },
        ]
        res = calculate_resource_snapshot(steps, GAME_CONFIG)
        assert not any("возврат" in v.lower() for v in res["violations"])

    def test_max_identical_streak_constraint(self) -> None:
        """Exceeding max_identical_steps (2) must trigger a violation."""
        steps = [
            {"card_code": "salary", "amount": 50000.0, "frequency": 1, "channel": "mobile"},
            {"card_code": "salary", "amount": 50000.0, "frequency": 1, "channel": "mobile"},
            {"card_code": "salary", "amount": 50000.0, "frequency": 1, "channel": "mobile"},
        ]
        res = calculate_resource_snapshot(steps, GAME_CONFIG)
        assert any("подряд" in v for v in res["violations"])

    def test_max_night_operations_constraint(self) -> None:
        """Exceeding max_night_operations (2) must trigger a violation."""
        steps = [
            {"card_code": "card_transfer", "amount": 10000.0, "frequency": 1, "channel": "mobile", "context": {"time_of_day": "night"}},
            {"card_code": "crypto_exchange", "amount": 10000.0, "frequency": 1, "channel": "web", "context": {"time_of_day": "night"}},
            {"card_code": "online_purchase", "amount": 10000.0, "frequency": 1, "channel": "web", "context": {"time_of_day": "night"}},
        ]
        res = calculate_resource_snapshot(steps, GAME_CONFIG)
        assert any("ночью" in v.lower() for v in res["violations"])

    def test_overdraft_balance_exhaustion(self) -> None:
        """Spending more money than available balance must trigger negative balance violation."""
        steps = [
            {"card_code": "card_transfer", "amount": 200000.0, "frequency": 1, "channel": "web"},
            {"card_code": "card_transfer", "amount": 200000.0, "frequency": 1, "channel": "web"},
        ]
        res = calculate_resource_snapshot(steps, GAME_CONFIG)
        assert float(res["resources_after"]["balance"]) < 0
        assert any("недостаточно денег" in v.lower() for v in res["violations"])

    def test_complete_valid_winning_chain(self) -> None:
        """Construct a complete valid scenario that reaches target outflow without violations."""
        steps = [
            {"card_code": "salary", "amount": 100000.0, "frequency": 1, "channel": "mobile", "context": {"has_documents": True}},
            {"card_code": "card_transfer", "amount": 80000.0, "frequency": 1, "channel": "mobile", "context": {"recipient_type": "known_counterparty"}},
            {"card_code": "online_purchase", "amount": 30000.0, "frequency": 1, "channel": "web", "context": {"has_documents": True}},
            {"card_code": "crypto_exchange", "amount": 45000.0, "frequency": 1, "channel": "web", "context": {"country_risk": "low"}},
        ]
        res = calculate_resource_snapshot(steps, GAME_CONFIG)
        assert len(res["violations"]) == 0, f"Expected 0 violations, got: {res['violations']}"
        assert float(res["totals"]["gross_outflow"]) >= 150000.0, "Target outflow must be met"
        assert res["resources_after"]["energy"] >= 0
        assert res["resources_after"]["time"] >= 0
        assert res["resources_after"]["trust"] > 0
