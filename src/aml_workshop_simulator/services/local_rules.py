from __future__ import annotations

from typing import Any

INITIAL_BALANCE = 250_000.0
INITIAL_ENERGY = 14
INITIAL_TIME = 18
INITIAL_TRUST = 100
MAX_ACTIONS = 8
MAX_IDENTICAL_STEPS = 2
MAX_NIGHT_OPERATIONS = 2
TARGET_OUTFLOW = 150_000.0

ROUND_LIMITS = {
    "cash": {"label": "Наличные операции", "limit": 150_000.0},
    "international": {"label": "Международные переводы", "limit": 180_000.0},
    "crypto": {"label": "Криптовалюта", "limit": 100_000.0},
    "anonymous": {"label": "Анонимные получатели", "limit": 75_000.0},
    "high_risk_country": {"label": "Страны высокого риска", "limit": 100_000.0},
}

CHANNEL_LABELS = {
    "bank": "Банковское отделение",
    "branch": "Банковское отделение / Касса",
    "atm": "Банкомат / Терминал",
    "mobile": "Мобильный банк / СБП",
    "web": "Интернет-банк",
    "pos": "Терминал оплаты (POS)",
    "exchange": "Криптобиржа / Обменник",
}

COUNTRY_RISK_LABELS = {
    "low": "Низкий риск юрисдикции",
    "medium": "Средний риск юрисдикции",
    "high": "Высокий риск (Офшор / Санкции)",
}

RECIPIENT_TYPE_LABELS = {
    "known_counterparty": "Проверенный контрагент",
    "new_counterparty": "Новый контрагент",
    "anonymous_wallet": "Анонимный кошелек / Дроп",
}

TIME_OF_DAY_LABELS = {
    "day": "Дневное время (09:00 - 18:00)",
    "evening": "Вечернее время (18:00 - 23:00)",
    "night": "Ночное время (23:00 - 06:00)",
}

VELOCITY_LABELS = {
    "spaced": "Интервальный темп",
    "normal": "Обычный темп",
    "rapid": "Быстрый / Веерный темп",
}

ACTION_CARDS: list[dict[str, Any]] = [
    {
        "id": 1,
        "code": "salary",
        "version": 1,
        "title": "Получить зарплату",
        "category": "Поступление",
        "description": "Регулярное поступление от известного работодателя.",
        "weight": 0.0,
        "risk_weight": 0.0,
        "flow": "credit",
        "energy_cost": 1,
        "time_cost": 1,
        "trust_cost": 0,
        "fee_rate": 0.0,
        "min_amount": 10_000.0,
        "max_amount": 150_000.0,
        "max_frequency": 2,
        "round_frequency_limit": 2,
        "requires_card_code": None,
        "channels": ["bank", "branch", "mobile"],
    },
    {
        "id": 2,
        "code": "cash_deposit",
        "version": 1,
        "title": "Внести наличные",
        "category": "Наличные",
        "description": "Пополнение счета через банкомат или кассу.",
        "weight": 12.0,
        "risk_weight": 12.0,
        "flow": "credit",
        "energy_cost": 2,
        "time_cost": 2,
        "trust_cost": 5,
        "fee_rate": 0.0,
        "min_amount": 5_000.0,
        "max_amount": 150_000.0,
        "max_frequency": 3,
        "round_frequency_limit": 3,
        "requires_card_code": None,
        "channels": ["atm", "branch"],
    },
    {
        "id": 3,
        "code": "card_transfer",
        "version": 1,
        "title": "Перевести по карте",
        "category": "Перевод",
        "description": "Перевод другому клиенту банка.",
        "weight": 5.0,
        "risk_weight": 5.0,
        "flow": "debit",
        "energy_cost": 1,
        "time_cost": 1,
        "trust_cost": 1,
        "fee_rate": 0.005,
        "min_amount": 1_000.0,
        "max_amount": 500_000.0,
        "max_frequency": 5,
        "round_frequency_limit": 7,
        "requires_card_code": None,
        "channels": ["mobile", "web", "branch"],
    },
    {
        "id": 4,
        "code": "international",
        "version": 1,
        "title": "Международный перевод",
        "category": "Перевод",
        "description": "Отправка средств в другую страну.",
        "weight": 18.0,
        "risk_weight": 18.0,
        "flow": "debit",
        "energy_cost": 3,
        "time_cost": 3,
        "trust_cost": 12,
        "fee_rate": 0.02,
        "min_amount": 5_000.0,
        "max_amount": 180_000.0,
        "max_frequency": 3,
        "round_frequency_limit": 3,
        "requires_card_code": None,
        "channels": ["web", "branch"],
    },
    {
        "id": 5,
        "code": "cash_withdrawal",
        "version": 1,
        "title": "Снять наличные",
        "category": "Наличные",
        "description": "Получение наличных вскоре после поступления.",
        "weight": 14.0,
        "risk_weight": 14.0,
        "flow": "debit",
        "energy_cost": 2,
        "time_cost": 2,
        "trust_cost": 8,
        "fee_rate": 0.01,
        "min_amount": 5_000.0,
        "max_amount": 120_000.0,
        "max_frequency": 4,
        "round_frequency_limit": 4,
        "requires_card_code": None,
        "channels": ["atm", "branch"],
    },
    {
        "id": 6,
        "code": "crypto_exchange",
        "version": 1,
        "title": "Купить криптовалюту",
        "category": "Цифровые активы",
        "description": "Перевод средств на криптовалютную площадку.",
        "weight": 20.0,
        "risk_weight": 20.0,
        "flow": "debit",
        "energy_cost": 3,
        "time_cost": 3,
        "trust_cost": 15,
        "fee_rate": 0.015,
        "min_amount": 5_000.0,
        "max_amount": 100_000.0,
        "max_frequency": 3,
        "round_frequency_limit": 3,
        "requires_card_code": None,
        "channels": ["exchange", "web"],
    },
    {
        "id": 7,
        "code": "online_purchase",
        "version": 1,
        "title": "Оплатить покупку",
        "category": "Покупка",
        "description": "Оплата товара в интернет-магазине.",
        "weight": 2.0,
        "risk_weight": 2.0,
        "flow": "debit",
        "energy_cost": 1,
        "time_cost": 1,
        "trust_cost": 0,
        "fee_rate": 0.0,
        "min_amount": 1_000.0,
        "max_amount": 250_000.0,
        "max_frequency": 5,
        "round_frequency_limit": 6,
        "requires_card_code": None,
        "channels": ["mobile", "web"],
    },
    {
        "id": 8,
        "code": "refund",
        "version": 1,
        "title": "Получить возврат",
        "category": "Поступление",
        "description": "Возврат возможен только после покупки в этой цепочке.",
        "weight": 4.0,
        "risk_weight": 4.0,
        "flow": "credit",
        "energy_cost": 1,
        "time_cost": 1,
        "trust_cost": 2,
        "fee_rate": 0.0,
        "min_amount": 1_000.0,
        "max_amount": 150_000.0,
        "max_frequency": 3,
        "round_frequency_limit": 3,
        "requires_card_code": "online_purchase",
        "channels": ["mobile", "web"],
    },
]

RECIPIENT_TRUST_COST = {
    "known_counterparty": 0,
    "new_counterparty": 3,
    "anonymous_wallet": 10,
}
COUNTRY_TRUST_COST = {"low": 0, "medium": 4, "high": 10}
TIME_TRUST_COST = {"day": 0, "evening": 2, "night": 7}
VELOCITY_TRUST_COST = {"spaced": 0, "normal": 1, "rapid": 7}
CHANNEL_TRUST_MODIFIER = {
    "bank": -2,
    "branch": -3,
    "mobile": 0,
    "web": 2,
    "atm": 2,
    "exchange": 4,
}
