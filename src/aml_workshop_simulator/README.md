# AML Workshop Simulator package

- `api/` — HTTP API;
- `core/` — технические настройки;
- `schemas/` — контракты данных;
- `services/` — бизнес-логика;
- `db/` — PostgreSQL persistence;
- `ui/` — два Streamlit-интерфейса.

Зависимости направляются от UI/API к services и далее к DB, а не наоборот.
