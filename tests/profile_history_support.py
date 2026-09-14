"""Observed, public stage-05 examples; not risk labels or dataset templates."""

from tests.purchase_support import purchase_config


def profile_config():
    config = purchase_config()
    behavior = config["behavior"]
    behavior["profile"] = {
        "id": "employed-client",
        "title": "Наёмный сотрудник",
        "description": "Получает зарплату и переводы от знакомых, оплачивает повседневные покупки. Другие доходы неизвестны.",
    }
    behavior["history"] = {
        "version": "observed-history-v1",
        "window_days": 30,
        "operations": [
            event("h1", "2026-08-14T09:00:00+03:00", "salary", "80000.00", "employer"),
            event(
                "h2", "2026-09-01T09:00:00+03:00", "incoming_transfer", "25000.50", "A"
            ),
            event("h3", "2026-09-02T12:00:00+03:00", "card_transfer", "10000.00", "A"),
            event("h4", "2026-09-03T18:00:00+03:00", "purchase", "3500.25", "shop"),
            event(
                "h5", "2026-09-12T23:59:00+03:00", "cash_withdrawal", "5000.00", None
            ),
        ],
    }
    return config


def event(identity, date, code, amount, party):
    return dict(
        id=identity,
        occurred_at=date,
        operation_code=code,
        amount=amount,
        counterparty_id=party,
        category=None,
    )
