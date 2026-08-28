# Database migrations

Alembic environment and immutable migration revisions live here. Production startup
must not call `create_all`; schema changes are applied by the dedicated migration job.

- `versions/` — ordered Alembic revisions;
- `seeds/` — idempotent card-version and bootstrap seed definitions.
