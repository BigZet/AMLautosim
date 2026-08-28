# Database models

SQLAlchemy-модели, обычно по одной основной таблице на файл:

- `users.py` — участники и администраторы;
- `sessions.py` — hash, expiry и revoke server-side сессий;
- `rounds.py` — раунды и immutable config snapshot;
- `scenarios.py` — цепочки, revision и resource snapshot;
- `results.py` — scoring results, adjustments и audit events.

API DTO и UI-модели сюда не помещаются.
