from src.aml_workshop_simulator.core.expanded_game import expanded_game_config
from src.aml_workshop_simulator.domain.catalog import SEED_CARD_CATALOG
from src.aml_workshop_simulator.ui.nicegui.participant_limits import limits_view


def test_limits_follow_round_overrides_and_enabled_operations():
    config = expanded_game_config()
    config["operations"] = [{"code": "salary", "version": 1, "max_occurrences": 4,
                             "min_amount": "2500", "max_amount": "7000", "fee_rate": "0.015"}]
    config["constraints"]["max_identical_steps"] = 3
    general, operations, _, additions = limits_view(config, SEED_CARD_CATALOG)
    assert ("Одинаковых операций подряд", "Не более 3") in general
    assert len(operations) == 1
    assert operations[0]["count"] == 4
    assert operations[0]["amount"] == "2 500–7 000 ₽"
    assert operations[0]["fee"] == "1,5%"
    assert not any(label == "Покупки за раунд" for label, _ in general)
    assert ("Ожидание 60 мин", "2 времени") in additions


def test_purchase_total_uses_published_configuration():
    config = expanded_game_config()
    config["behavior"]["purchases"]["max_total"] = "27500"
    general, operations, _, _ = limits_view(config, SEED_CARD_CATALOG)
    assert ("Покупки за раунд", "До 27 500 ₽") in general
    assert any(row["id"] == "purchase" for row in operations)


def test_participant_api_cost_shape():
    config = expanded_game_config()
    card = dict(SEED_CARD_CATALOG[0])
    card["costs"] = {"energy": card.pop("energy_cost"), "time": card.pop("time_cost")}
    _, rows, _, _ = limits_view(config, [card])
    assert rows[0]["energy"] == card["costs"]["energy"]
    assert rows[0]["time"] == card["costs"]["time"]
