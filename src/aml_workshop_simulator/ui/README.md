# Streamlit UI

- `participant/` — интерфейс участника;
- `admin/` — интерфейс администратора;
- `shared/` — общий API client, cookie adapter и session-state helpers.

Оба интерфейса получают канонические данные только через FastAPI и не импортируют
`db/` напрямую.
