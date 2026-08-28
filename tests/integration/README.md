# Integration tests

Проверки нескольких компонентов вместе:

- `test_auth_api.py` — FastAPI, sessions и PostgreSQL;
- `test_scenario_api.py` — GET/PUT/submit и revisions;
- `test_round_lifecycle.py` — draft, active, scoring, completed;
- `test_db_constraints.py` — indexes, locks и transactions;
- `test_migrations.py` — Alembic upgrade и idempotent seed;
- `test_ui_client.py` — typed Streamlit API client против API stub.

PostgreSQL-specific поведение не заменяется SQLite.
