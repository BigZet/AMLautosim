# Schemas

Pydantic-модели HTTP-запросов и ответов:

- `auth.py` — login/register/session DTO;
- `rounds.py` — round и card DTO;
- `scenarios.py` — шаги, revision и resource snapshot;
- `leaderboard.py` — результаты и позиции;
- `errors.py` — единый error envelope.

DTO не являются SQLAlchemy-моделями и не содержат бизнес-формул.
