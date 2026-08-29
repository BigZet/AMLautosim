# Deployment assets

- `Dockerfile` — общий образ приложения для всех четырёх ролей.

Один и тот же образ запускает `api`, `play` и `admin`: различаются только команда
запуска и health check в [`../docker-compose.yml`](../docker-compose.yml).

## Образ

Сборка двухстадийная. В первой стадии стоят компиляторы и `pip wheel` собирает все
зависимости в колёса; в runtime-стадии toolchain отсутствует, колёса ставятся
`--no-index`. Приложение работает под непривилегированным пользователем `app`
(uid 10001), каталог `/app` доступен только на чтение.

Что попадает в образ, ограничено [`../.dockerignore`](../.dockerignore): только
`alembic.ini`, `migrations/`, `scripts/`, `src/` и `.streamlit/`. Тесты, документация,
`resources/` и `.venv/` в build context не передаются.

## Секреты

Секреты не коммитятся и не попадают в слои образа: они передаются через `.env`
(см. [`../.env.example`](../.env.example)) и читаются compose во время запуска.

## Reverse proxy

Bundled compose публикует наружу только два Streamlit-порта; PostgreSQL и API
слушают `127.0.0.1`. Отдельного proxy/TLS в репозитории нет — целевая топология с
HTTPS, изолированными сетями и маршрутами `/play` и `/admin` описана в
[`../docs/deployment.md`](../docs/deployment.md) и настраивается на стороне VM.
