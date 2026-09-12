# Развёртывание через Docker Compose

Целевой runtime: Python 3.13, PostgreSQL 16, один процесс FastAPI и один NiceGUI.
Нужны Docker Engine и Compose с поддержкой `up --wait`.
Реверс-прокси, TLS, systemd и фактическое развёртывание на удалённой машине
в текущую подготовку не входят.

## Первый запуск

Из корня проекта скопировать `.env.example` в `.env`, задать три секрета:
`POSTGRES_PASSWORD`, `BOOTSTRAP_ADMIN_PASSWORD`, `NICEGUI_STORAGE_SECRET`.
Пароль администратора — 10–128 символов. Значения со знаками `$`, `#` и пробелами
заключать в одинарные кавычки; hex-генерация упрощает настройку.

```bash
docker compose config --quiet
docker compose up -d --build --wait
docker compose ps
curl --fail http://127.0.0.1:8000/health/ready
curl --fail http://127.0.0.1:8080/health/live
```

`db` становится healthy, затем API применяет миграции и seed, затем стартует UI.
Ошибка миграции, конфигурации или seed не допускает запуск API.
Seed обновляет каталог, создаёт отсутствующего администратора и игру в `draft`.
Существующие пароль, игра, сценарии и результаты сохраняются.

## Настройки

| Настройки | Потребитель и смысл |
| --- | --- |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | БД и API; пароль передаётся отдельно от URL |
| `POSTGRES_PORT`, `API_PORT`, `UI_PORT` | Порты хоста, по умолчанию 5432 / 8000 / 8080 |
| `SESSION_TTL_MINUTES` | API, срок входа, по умолчанию 240 |
| `LOGIN_MAX_FAILED_ATTEMPTS`, `LOGIN_LOCKOUT_MINUTES` | API, по умолчанию 10 / 5 |
| `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD` | Создание первого администратора |
| `NICEGUI_STORAGE_SECRET` | Постоянный секрет подписи cookie UI |
| `COOKIE_SECURE` | Атрибут Secure cookie UI; false для текущего HTTP-запуска |

Compose задаёт API `POSTGRES_HOST=db`, порт 5432; UI получает `API_URL=http://api:8000`,
`UI_HOST=0.0.0.0`, порт 8080 и путь `/home/app/nicegui` независимо от локальных настроек.
Для локальных Python-команд `DATABASE_URL` имеет приоритет над `POSTGRES_*`;
в URL пароль должен быть percent-encoded. Compose не использует `DATABASE_URL` из `.env`.
Менять пароль существующей БД одной правкой `.env` нельзя: сначала измените роль PostgreSQL.

PostgreSQL и API слушают на хосте только `127.0.0.1`; наружу опубликован UI.
UI не предоставляет маршруты `/api/v1/*`. Прямой HTTP предназначен для проверки
в доверенной сети; публичный HTTPS-доступ будет настроен отдельным этапом.
Не масштабировать NiceGUI несколькими процессами: текущая схема использует
локальное серверное состояние и WebSocket одного процесса.

## Хранение и обновление

`postgres_data` сохраняет БД, `nicegui_data` — серверные UI-сессии.
Сохраняйте секрет NiceGUI при перезапуске. Команда `down` сохраняет тома;
`down -v` удаляет их и не является командой обычного обновления.
Инструкции обновления и восстановления: [operations.md](operations.md).

Начальная миграция поддерживает чистую БД и текущую ревизию
`0001_current_schema`; автоматического переноса прежней схемы разработки нет.
Очистка проекта не требует сброса существующей игры текущего формата.

## Проверка сборки

```bash
docker compose build --no-cache
docker compose run --rm --no-deps api python -m pip check
docker compose exec api alembic check
python scripts/check_nicegui_transport.py --url http://127.0.0.1:8080
```

Последняя команда выполняется из окружения с зависимостями проекта.
Она проверяет страницу, cookie и настоящий WebSocket handshake; браузерные
сценарии и тесты описаны в [testing-strategy.md](testing-strategy.md).
