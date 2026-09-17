"""Game-feasible route families, without assigned class or private profiles."""

from copy import deepcopy
from functools import lru_cache
import random
from uuid import NAMESPACE_URL, uuid5

from scripts.build_aml_fixed_history_dataset import common_context

EXTRA_ROUTES = (
    (
        "irregular_prepaid",
        "T:75000 T:70000 I:80000 T:55000 T:50000 I:80000 T:65000 I:80000 T:45000 T:40000",
        {},
    ),
    (
        "staged_six",
        "T:75000 T:70000 I:80000 T:65000 I:80000 T:60000 T:60000 I:80000 T:70000",
        {4: 1440},
    ),
    (
        "cash_reserve",
        "W:50000 T:60000 W:60000 I:80000 T:40000 I:80000 T:50000 T:55000 I:80000 T:45000 T:40000",
        {},
    ),
    (
        "salary_liquidity",
        "S:25000 T:80000 T:80000 I:80000 T:60000 T:60000 I:80000 T:60000 I:80000 T:60000",
        {},
    ),
    (
        "purchase_with_irregular",
        "T:75000 T:70000 I:80000 P:3000 T:55000 T:50000 I:80000 T:65000 I:80000 T:45000 T:40000",
        {},
    ),
    (
        "cash_then_pause",
        "W:60000 T:80000 I:80000 T:50000 I:80000 W:60000 T:70000 I:80000 T:80000",
        {6: 1440},
    ),
    (
        "seven_repeated",
        "T:54000 T:54000 I:80000 T:54000 T:54000 I:80000 T:54000 T:54000 I:80000 T:76000",
        {},
    ),
    (
        "eight_repeated",
        "T:50000 T:50000 I:80000 T:50000 T:50000 I:80000 T:50000 T:50000 I:80000 T:50000 T:50000",
        {},
    ),
    (
        "slow_eight_repeated",
        "T:50000 T:50000 I:80000 T:50000 T:50000 I:80000 T:50000 T:50000 I:80000 T:50000 T:50000",
        {4: 60, 7: 60, 10: 60},
    ),
)


@lru_cache(maxsize=1)
def catalog():
    config, fixtures = common_context()
    templates = [
        (f"fixture-{i:02d}", deepcopy(t["steps"])) for i, t in enumerate(fixtures)
    ]
    kinds = {
        "I": (2, "incoming_transfer"),
        "T": (3, "card_transfer"),
        "W": (4, "cash_withdrawal"),
        "S": (1, "salary"),
        "P": (5, "purchase"),
    }
    for name, recipe, waits in EXTRA_ROUTES:
        steps = []
        for n, token in enumerate(recipe.split(), 1):
            kind, amount = token.split(":")
            card_id, code = kinds[kind]
            steps.append(
                dict(
                    step_id=str(uuid5(NAMESPACE_URL, f"curriculum/{name}/{n}")),
                    card=dict(id=card_id, code=code, version=1),
                    amount=amount,
                    context={},
                    action_details={},
                    interval_minutes=None if n == 1 else waits.get(n, 1),
                )
            )
        templates.append((name, steps))
    return config, templates


def candidate(seed):
    rng = random.Random(seed)
    config, templates = catalog()
    family = seed % len(templates)
    _, prototype = templates[family]
    steps = deepcopy(prototype)
    topology = (seed // len(templates)) % 5
    parties = list("ABCD")
    rng.shuffle(parties)
    # Some variants preserve the designed route; others explore actual waiting costs.
    preserve_timing = rng.random() < 0.5
    for i, step in enumerate(steps):
        code = step["card"]["code"]
        step["context"] = {}
        step.pop("claim_id", None)
        step["purpose_code"] = "shared_expense"
        if not preserve_timing:
            step["interval_minutes"] = (
                None if i == 0 else rng.choices([1, 10, 60, 1440], [12, 3, 3, 1])[0]
            )
        if code == "incoming_transfer":
            step["sender_id"] = (
                parties[0] if topology in (0, 3) else rng.choice(parties)
            )
            step["action_details"] = dict(
                incoming_kind="bank_transfer", bank_country="RU"
            )
        elif code == "card_transfer":
            step["recipient_id"] = (
                parties[0]
                if topology in (1, 3)
                else parties[1]
                if topology == 0
                else rng.choice(parties)
            )
            step["action_details"] = {}
        elif code == "salary":
            step["sender_id"] = "employer"
            step["action_details"] = dict(income_basis="payroll_registry")
            step["purpose_code"] = "salary"
        else:
            step["action_details"] = {}
            step["purpose_code"] = "personal_spending"
            if code == "purchase":
                step["recipient_id"] = "shop"
    # Amount-conserving legal-range mutations; full financial engine validates fees.
    cards = [s for s in steps if s["card"]["code"] == "card_transfer"]
    if len(cards) >= 2:
        left, right = rng.sample(cards, 2)
        delta = rng.randint(-500, 500)
        a, b = int(float(left["amount"])) + delta, int(float(right["amount"])) - delta
        if 10000 <= a <= 80000 and 10000 <= b <= 80000:
            left["amount"], right["amount"] = str(a), str(b)
    return config, steps, family, topology
