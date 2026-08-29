# Test suites

- `unit/` — правила раунда, политика операций, скоринг и DTO без БД и сети;
- `contract/` — соответствие ответов FastAPI задокументированным DTO;
- `integration/` — FastAPI + PostgreSQL 16 + Alembic: жизненный цикл раунда, версии
  черновиков, изоляция и приватность;
- `ui/` — реальный браузер против реального стека (PostgreSQL + FastAPI + два Streamlit);
- `e2e/` — полный прогон мероприятия, включая перезапуск процессов и бэкап.

## Как запускать

Всё, кроме `unit/`, требует поднятой PostgreSQL 16 (`docker compose up -d db`) и
переменной `TEST_ADMIN_DATABASE_URL`, если БД не на `localhost:5432` с ролью `aml`.

```bash
# быстрые проверки без БД
python -m pytest tests/unit -q

# API и база
python -m pytest tests/integration tests/contract -q

# браузерные проверки: поднимают собственный стек на свободных портах
python -m pytest tests/ui -q

# только Selenium-набор авторизации
python -m pytest tests/ui/test_selenium_auth.py -q

# сквозной прогон мероприятия (часть тестов требует docker)
python -m pytest tests/e2e -q
```

Браузерные наборы используют Chrome/chromedriver (Selenium) и Chromium (Playwright).
Зависимости ставятся из `requirements-dev.txt`; браузер Playwright — командой
`python -m playwright install chromium`. Если браузер недоступен, соответствующие
наборы помечаются как skipped, а не падают.

При падении браузерного теста в `tests/artifacts/` сохраняются скриншот, HTML страницы
и лог консоли (Playwright дополнительно пишет trace-архив).

Нагрузочные, security и contract-проверки оформляются обычными тестовыми файлами в
подходящем уровне. Отдельный каталог заводится только тогда, когда таких файлов станет
действительно много.
