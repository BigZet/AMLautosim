# Структура проекта

| Каталог | Назначение |
| --- | --- |
| `src/aml_workshop_simulator/api` | FastAPI, маршруты, зависимости доступа и ошибки |
| `src/aml_workshop_simulator/core` | Настройки, сессии, общие ошибки и конфигурация |
| `src/aml_workshop_simulator/domain` | Игровые модели, проверка структуры, ресурсы и скоринг |
| `src/aml_workshop_simulator/services` | Прикладные команды, запросы и проекции |
| `src/aml_workshop_simulator/schemas` | Pydantic-контракты API и конфигурации |
| `src/aml_workshop_simulator/db` | SQLAlchemy-модели, соединения и общие запросы |
| `src/aml_workshop_simulator/ui/nicegui` | Единый UI участника и организатора, HTTP-клиент |
| `config` | Каталог и игровые настройки JSON |
| `migrations` | Начальная схема и Alembic |
| `scripts` | Seed, валидация, баланс, transport smoke; отдельные команды офлайн-обучения и оценки |
| `tests` | Unit, API, компоненты NiceGUI, нагрузка; `tests/ml` в отдельном ML-окружении |
| `deploy` | Dockerfile приложения и отдельный Dockerfile.ml |
| `resources` | Единственная текущая модель и её реестр |

Точки запуска: `src.aml_workshop_simulator.api.main:app` и
`python -m src.aml_workshop_simulator.ui.nicegui.app`.
UI общается с API по HTTP и не обращается к БД или игровому домену напрямую.
Маршруты FastAPI и страницы NiceGUI регистрируются декораторами.

`domain/rules.py` — фасад ресурсного движка. Текущий классификатор загружается
через `services/game_classifier.py`. Отдельный worker выполняет устойчивые
задания скоринга. Миграции схемы БД сохраняются для корректного развёртывания.
