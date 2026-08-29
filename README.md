# AML Workshop Simulator

Учебный симулятор AML для 45-минутного мастер-класса: участники собирают цепочки
финансовых операций, сервер детерминированно считает риск и ресурсы, организатор
управляет раундом и лидербордом.

```text
Browser -> Streamlit (participant / admin) -> FastAPI -> PostgreSQL 16
```

## Структура

- [`src/`](src/) — production-код модульного монолита (API, домен, сервисы, БД, оба UI);
- [`migrations/`](migrations/) — Alembic-миграции;
- [`tests/`](tests/) — unit, contract, integration, UI и E2E проверки;
- [`deploy/`](deploy/) и [`scripts/`](scripts/) — образ приложения и служебные скрипты;
- [`resources/`](resources/) — сгенерированные датасеты для обучения ML-модели;
- [`docs/`](docs/) — архитектурная и продуктовая документация.

## Быстрый старт

```bash
cp .env.example .env
```

Заполните в `.env` обязательные секреты (`POSTGRES_PASSWORD`,
`BOOTSTRAP_ADMIN_PASSWORD`) — без них стек не стартует намеренно. Затем:

```bash
docker compose up -d --build
```

Поднимаются четыре сервиса: PostgreSQL, API, интерфейс участника и панель
организатора. Миграции и идемпотентный seed выполняются автоматически при старте
`api`. Порты PostgreSQL и API публикуются только на `127.0.0.1`; наружу смотрят
только два Streamlit-интерфейса.

| Сервис | Адрес |
| --- | --- |
| Интерфейс участника | http://localhost:8501 |
| Панель организатора | http://localhost:8502 |
| API (только с хоста) | http://127.0.0.1:8000/api/v1/docs |

Развертывание на VM, TLS и reverse proxy описаны в
[`docs/deployment.md`](docs/deployment.md), эксплуатация — в
[`docs/operations.md`](docs/operations.md).

## Разработка

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

Карта production-структуры — в
[`docs/project-structure.md`](docs/project-structure.md), навигация по документации —
в [`docs/README.md`](docs/README.md), запуск тестов — в [`tests/README.md`](tests/README.md).
