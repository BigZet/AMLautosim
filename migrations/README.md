# Database migrations

Alembic environment and immutable migration revisions live here. Production startup
must not call `create_all`; the schema is applied by `python -m scripts.seed_database
--migrate`, which the `api` service runs before uvicorn.

- `versions/` — ordered Alembic revisions; see `versions/README.md` for the chain.

Initial data (card versions, bootstrap administrator, demo round) is seeded
idempotently by `scripts/seed_database.py`, not by a migration.
