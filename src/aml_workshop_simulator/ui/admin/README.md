# Admin UI

Интерфейс администратора:

- `app.py` — Streamlit entry point и навигация;
- `rounds.py` — настройка и активация раунда;
- `participants.py` — список, детали и block/unblock;
- `scoring.py` — readiness и запуск scoring;
- `leaderboard.py` — base/effective значения и adjustments;
- `audit.py` — журнал административных действий.

Опасные команды требуют подтверждения и read-back после неопределенного timeout.
