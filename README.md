# AML Workshop Simulator

> Датасеты JSONL/CSV и модели CBM хранятся через Git LFS. Перед сборкой или проверками установите Git LFS и выполните `git lfs install`, затем `git lfs pull` в клонированном репозитории.

Учебный симулятор для мастер-класса: участники собирают цепочки операций,
FastAPI рассчитывает ресурсы и риск, организатор управляет игрой и рейтингом.

Текущий выпуск: `aml-game-attribute-context-v1`, 28 признаков, контракт v10.
Новые игры оцениваются по соответствию учебным AML-паттернам. История общая
и неизменная; прежние раунды сохраняют закреплённые модели.
[Итоговые проверки и актуальные артефакты](docs/verification/aml-classifier-v1/README.md).

```text
Браузер → NiceGUI (:8080, /play и /admin) → FastAPI (:8000) → PostgreSQL 16
```

## Запуск через Docker Compose

```bash
cp .env.example .env
```

Заполните `POSTGRES_PASSWORD`, `BOOTSTRAP_ADMIN_PASSWORD` (10–128 символов)
и `NICEGUI_STORAGE_SECRET`. Для генерации используйте `openssl rand -hex 32`.
Секреты со специальными символами заключайте в одинарные кавычки в `.env`.

```bash
docker compose up -d --build --wait
```

Участник: http://localhost:8080/play. Организатор: http://localhost:8080/admin.
Адрес организатора задаёт `BOOTSTRAP_ADMIN_EMAIL`. API и БД опубликованы только
на loopback; Swagger: http://127.0.0.1:8000/api/v1/docs.
Миграции и идемпотентный seed выполняются перед запуском API.

Текущий запуск использует HTTP. Настройка реверс-прокси и HTTPS — отдельный этап.

## Разработка и документация

Python 3.13. `requirements.in` содержит прямые зависимости,
`requirements.txt` фиксирует полный runtime-набор, `requirements-dev.txt` — инструменты проверок.

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check src scripts tests migrations
.venv/bin/python -m pytest -q tests/unit
```

В Windows PowerShell используйте `.venv\Scripts\python.exe` и включите UTF-8
перед установкой, тестами и запуском приложения:

```powershell
$env:PYTHONUTF8 = '1'
uv python install 3.13
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest -q tests/unit
```

Для локального запуска без Docker нужна PostgreSQL 16 и заполненный `.env`.
После создания базы выполните миграции, затем запустите API и UI в отдельных
терминалах с `$env:PYTHONUTF8 = '1'`:

```powershell
.venv/Scripts/python.exe -m scripts.seed_database --wait-for-db --migrate
.venv/Scripts/python.exe -m uvicorn src.aml_workshop_simulator.api.main:app --host 127.0.0.1 --port 8000
# В другом терминале: dotenv передаёт настройки .env интерфейсу NiceGUI.
.venv/Scripts/python.exe -m dotenv -f .env run -- .venv/Scripts/python.exe -m src.aml_workshop_simulator.ui.nicegui.app
```

Файлы, проверяемые по контрольным суммам модели, должны сохранять окончания
строк LF; это закреплено в `.gitattributes`. Тест защиты от символических ссылок
в Windows пропускается, если системе не разрешено их создание.

- [Развёртывание](docs/deployment.md) и [эксплуатация](docs/operations.md).
- [NiceGUI](docs/nicegui.md), [архитектура](docs/architecture.md), [API](docs/api.md).
- [Конфигурация](config/README.md), [баланс](config/BALANCE.md), [тесты](tests/README.md).
- [Все документы](docs/README.md) и [структура проекта](docs/project-structure.md).

Текущий выпуск игры использует CatBoost для оценки риска и SHAP для объяснений.
Пакет `resources/catboost_models/integration-v2-final` входит в серверный образ
и проверяется при старте API; без исправного пакета приложение не запускается.
Обучающий датасет в runtime-образ не включён. Ресурсы и итоговая формула рейтинга
рассчитываются по правилам снимка игры.

[Качество и ограничения модели](docs/verification/catboost-behavior-v2.md),
[команды воспроизведения и пакет](docs/catboost-behavior-model.md),
[отчёт интеграции CatBoost и SHAP](docs/verification/catboost-shap-integration.md).
[Первая офлайн-модель](docs/verification/catboost-training-v1.md) сохранена как исторический эксперимент.
