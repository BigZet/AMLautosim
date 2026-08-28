# Core

Общие технические настройки:

- `config.py` — Pydantic Settings и переменные окружения;
- `security.py` — password hashing и генерация session token;
- `logging.py` — JSON-логи и фильтрация PII;
- `constants.py` — только технические константы.

Игровые правила и лимиты должны находиться в `services/` или versioned ruleset.
