# AML Workshop Simulator

Репозиторий разделен на следующие основные области:

- [`src/`](src/) — production-код модульного монолита;
- [`migrations/`](migrations/) — Alembic-миграции и идемпотентные seed-данные;
- [`tests/`](tests/) — unit, contract, integration, UI, E2E, load и security проверки;
- [`deploy/`](deploy/) и [`scripts/`](scripts/) — развертывание и автоматизация;
- [`docs/`](docs/) — архитектурная и продуктовая документация;
- [`mvp/`](mvp/) — автономный MVP интерфейса на Streamlit, сохраненный как референс.

Карта production-структуры описана в [`docs/project-structure.md`](docs/project-structure.md).
Инструкции запуска MVP находятся в [`mvp/README.md`](mvp/README.md). Навигация по
документации — в [`docs/README.md`](docs/README.md).
