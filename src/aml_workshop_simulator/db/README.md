# Database

Доступ к PostgreSQL через SQLAlchemy:

- `session.py` — engine, pool и фабрика DB sessions;
- `base.py` — declarative base и naming convention;
- `models/` — описание таблиц;
- `repositories/` — запросы, блокировки и сохранение данных.

Alembic revisions хранятся в корневом `migrations/`.
