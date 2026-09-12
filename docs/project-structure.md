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
| `scripts` | Seed, валидация, баланс и transport smoke |
| `tests` | Unit, API, компоненты NiceGUI и нагрузка |
| `deploy` | Dockerfile |
| `resources` | Отложенные примеры CatBoost, вне runtime |

Точки запуска: `src.aml_workshop_simulator.api.main:app` и
`python -m src.aml_workshop_simulator.ui.nicegui.app`.
UI общается с API по HTTP и не обращается к БД или игровому домену напрямую.
Маршруты FastAPI и страницы NiceGUI регистрируются декораторами.

`domain/rules.py` — используемый фасад движка, в том числе для отложенного
CatBoost-адаптера. Адаптер и генератор датасетов сохранены, но не включены в образ.
Неиспользуемые слои и второй UI не поддерживаются.
