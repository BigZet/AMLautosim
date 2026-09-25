from copy import deepcopy
from uuid import UUID

import pytest

from src.aml_workshop_simulator.domain.russian_plural import russian_plural


@pytest.mark.parametrize(
    "value,word",
    [
        (1, "шаг"),
        (2, "шага"),
        (5, "шагов"),
        (11, "шагов"),
        (21, "шаг"),
        (22, "шага"),
        (25, "шагов"),
        (0, "шагов"),
        (-21, "шаг"),
    ],
)
def test_russian_integer_plural(value, word):
    assert russian_plural(value, "шаг", "шага", "шагов") == word


def test_scenario_message_uses_plural_without_changing_limit():
    from tests.preparation_support import cases, outcome

    config, source = next(
        (config, steps) for name, config, steps in cases() if name == "v8-16"
    )
    steps = [deepcopy(source[i % len(source)]) for i in range(21)]
    for i, step in enumerate(steps):
        step["step_id"] = str(UUID(int=i + 1))
        step["interval_minutes"] = None if i == 0 else 1
    snapshot = outcome(config, steps)["snapshot"]
    violation = next(
        v for v in snapshot["violations"] if v["reason"] == "max_actions_exceeded"
    )
    assert violation["message"].startswith("В цепочке 21 шаг,")
    assert violation["current"] == "21"
    assert violation["allowed"] == "14"
