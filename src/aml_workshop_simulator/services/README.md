# Services

Бизнес-правила и прикладные сценарии:

- `auth.py` — регистрация, login и lifecycle сессий;
- `rounds.py` — создание, настройка и активация раунда;
- `scenarios.py` — revision, валидация, сохранение и submit;
- `scoring.py` — риск, ресурсы, объяснения и batch scoring;
- `leaderboard.py` — ranking и admin overlay.

Сервис принимает бизнес-решение и координирует транзакцию, но не знает о Streamlit.
