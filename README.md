# AML Workshop Simulator

> Текущая модель CBM хранится через Git LFS. Перед сборкой или проверками установите Git LFS и выполните `git lfs install`, затем `git lfs pull` в клонированном репозитории.

Учебный симулятор для мастер-класса: участники собирают цепочки операций,
FastAPI рассчитывает ресурсы и риск, организатор управляет игрой и рейтингом.

Зафиксированный выпуск: **2.0.0**, модель `aml-game-organizer-settings-v1`,
28 признаков, контракт v10.
Новые игры оцениваются по соответствию учебным AML-паттернам. История общая
и неизменная в пределах игры. Поддерживается только текущая модель;
прежние раунды и пакеты выведены из эксплуатации.
[Итоговые проверки и актуальные артефакты](docs/current-release.md).

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

Текущий выпуск использует CatBoost и SHAP. Единственный пакет
`resources/catboost_models/aml-game-organizer-settings-v1` входит в серверный образ
и проверяется при старте API. Прежние модели, датасеты и архивные результаты
экспериментов удалены. Перечень моделей — `resources/catboost_models/registry.json`.

[Состав выпуска](docs/current-release.md), [контракт модели](docs/operations/model-support.md).
