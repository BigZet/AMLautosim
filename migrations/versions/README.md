# Текущая схема

`0001_current_schema.py` — единственная начальная ревизия (`down_revision = None`).
Создаёт `users`, `sessions`, `action_cards`, `rounds`, `scenarios`,
`scoring_results`, `audit_events` сразу в актуальном виде.

Старые цепочки миграций и преобразования демонстрационных данных удалены.
Порядок запуска описан в [migrations/README.md](../README.md).
