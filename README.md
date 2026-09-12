# AML Workshop Simulator

Учебный симулятор для мастер-класса: участники собирают цепочки операций,
FastAPI рассчитывает ресурсы и риск, организатор управляет игрой и рейтингом.

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

- [Развёртывание](docs/deployment.md) и [эксплуатация](docs/operations.md).
- [NiceGUI](docs/nicegui.md), [архитектура](docs/architecture.md), [API](docs/api.md).
- [Конфигурация](config/README.md), [баланс](config/BALANCE.md), [тесты](tests/README.md).
- [Все документы](docs/README.md) и [структура проекта](docs/project-structure.md).

CatBoost отложен. Адаптер и примеры сохранены в исходниках, серверный образ
их не включает. Текущий скоринг детерминированный, без ML-модели.
