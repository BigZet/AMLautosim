# Документация

Документы описывают текущий стек FastAPI + NiceGUI + PostgreSQL 16.

- [Проведение игры](workshop-flow.md), [NiceGUI](nicegui.md).
- [Архитектура](architecture.md), [структура](project-structure.md), [решения](decisions.md).
- [API](api.md), [данные](data-model.md), [скоринг и рейтинг](scoring-and-leaderboard.md).
- [Сессии](sessions-and-cookies.md), [безопасность](security.md).
- [Развёртывание](deployment.md), [эксплуатация](operations.md).
- [Стратегия проверок](testing-strategy.md), [команды тестов](../tests/README.md).
- [Игровая конфигурация](../config/README.md), [баланс](../config/BALANCE.md).

[Отчёт очистки и контейнерной проверки](verification/deployment-cleanup.md).

В `verification/` находятся датированные отчёты. Они фиксируют проверки конкретной
версии и не подтверждают состояние последующих изменений или целевого сервера.
CatBoost и реверс-прокси остаются отдельными этапами.
