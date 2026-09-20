# Документация

Документы описывают текущий стек FastAPI + NiceGUI + PostgreSQL 16.

- [Проведение игры](workshop-flow.md), [NiceGUI](nicegui.md).
- [Пожелания к дизайну и ориентир для следующих страниц](ui-style-guide.md).
- [Архитектура](architecture.md), [структура](project-structure.md), [решения](decisions.md).
- [API](api.md), [данные](data-model.md), [скоринг и рейтинг](scoring-and-leaderboard.md).
- [Сессии](sessions-and-cookies.md), [безопасность](security.md).
- [Развёртывание](deployment.md), [эксплуатация](operations.md).
- [Поэтапное расширение AML-поведения](plans/aml-behavior/README.md).
- [Новый цикл: аудит смысла операций, интерфейса и диапазона оценок](plans/aml-behavior/09-semantic-and-interface-audit.md).
- [Результаты аудита: 79 сочетаний операций и диагностика близких оценок](verification/semantic-interface-audit/README.md).
- [Исправления v9: интерфейс, контракт и восемь оценок для согласования](verification/semantic-v9/README.md).
- [Новый датасет: подготовка и совместный разбор](verification/aml-dataset-stage07-review-ready.md).
- [Пилот: 2000 сценариев и страница проверки](verification/aml-pilot-stage07.md).
- [Этап 08 завершён: совместимость, Python 3.13 и восстановление](verification/aml-release-stage08.md).
- [Этап 07 завершён: итоговый датасет 20000 и ограничения](verification/aml-dataset-stage07-final.md).
- [Обучение CatBoost: команды и протокол](catboost-training.md).
- [Первая модель: результаты и ограничения](verification/catboost-training-v1.md).
- [План синтетического датасета для CatBoost](catboost-synthetic-dataset-plan.md).
- [AML-поведение: источники и применение к датасету](aml-behavior-research-2026.md).
- [Стратегия проверок](testing-strategy.md), [команды тестов](../tests/README.md).
- [Игровая конфигурация](../config/README.md), [баланс](../config/BALANCE.md).

[Допуск расширенной игры: интерфейс и баланс](verification/aml-interface-balance-stage06.md).

[Отчёт очистки и контейнерной проверки](verification/deployment-cleanup.md).

В `verification/` находятся датированные отчёты. Они фиксируют проверки конкретной
версии и не подтверждают состояние последующих изменений или целевого сервера.
CatBoost и SHAP подключены к игре. Готовность конкретного Docker-релиза фиксируется отдельной проверкой; настройки внешнего сервера и TLS проверяются перед деплоем.

- [Итоговая модель поведения v2: качество и ограничения](verification/catboost-behavior-v2.md).
- [Воспроизведение и пакет будущей интеграции](catboost-behavior-model.md).

- [CatBoost и SHAP подключены: проверки и выпуск](verification/catboost-shap-integration.md).

- [Полный аудит перед деплоем: замечания и повторные проверки](verification/full-audit/README.md).

- [Исправления полного аудита: 428 тестов и проверка в браузере](verification/audit-fixes/README.md).

- [Удаление лимитов ночных операций и анонимных получателей](verification/aml-classifier-v1/retired-limits-2026-09-18.md).

- [Аудит перед деплоем 20.09.2026](verification/predeploy-2026-09-20/04-readiness.md).
