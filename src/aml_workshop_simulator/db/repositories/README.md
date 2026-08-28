# Repositories

SQLAlchemy-запросы и PostgreSQL-specific операции:

- `users.py` — поиск и блокировка пользователя;
- `sessions.py` — lookup, revoke и cleanup;
- `rounds.py` — active round и `FOR UPDATE`;
- `scenarios.py` — optimistic revision и сохранение steps;
- `results.py` — scoring results и leaderboard queries.

Repository работает с хранением, но не решает, разрешен ли бизнес-переход.
