# Упрощенная структура production-проекта

Проект остается модульным монолитом, но без лишнего количества архитектурных слоев.
Код разделяется по шести понятным областям.

```text
.
├── src/aml_workshop_simulator/
│   ├── api/                       # FastAPI, routers, middleware, dependencies
│   ├── core/                      # настройки, безопасность, метаданные запроса
│   ├── schemas/                   # Pydantic request/response DTO
│   ├── domain/                    # правила игры, каталог, политика раунда
│   ├── services/                  # use cases поверх домена и БД
│   ├── db/                        # SQLAlchemy, repositories, DB session
│   └── ui/
│       ├── shared/                # API client, cookies, тема, браузерные заголовки
│       ├── participant/           # participant Streamlit
│       └── admin/                 # admin Streamlit
├── migrations/                    # Alembic и seed-данные
├── resources/                     # rulesets и синтетические fixtures
├── deploy/                        # Compose и reverse proxy
├── scripts/                       # небольшие служебные скрипты
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── docs/
└── mvp/                           # UI-референс, не production dependency
```

## Где что хранить

### `api/`

HTTP-слой FastAPI. В `api/main.py` создается приложение, в `api/routers/` лежат
`auth.py`, `rounds.py`, `scenarios.py` и admin endpoints. `deps.py` предоставляет
текущую сессию и сервисы, `middleware.py` отвечает за request ID и error envelope.

Router разбирает HTTP-запрос и вызывает service. SQL и игровые формулы в router не
помещаются.

### `core/`

Общие технические настройки: `config.py`, `security.py`, `enums.py`,
`request_meta.py` (адрес клиента и браузерные заголовки с учетом trusted proxies).
Игровые лимиты сюда не относятся: они должны быть частью versioned ruleset.

### `domain/`

Чистые правила, не знающие ни про HTTP, ни про SQLAlchemy:

- `catalog.py` — каталог операций и их параметров, включая набор из шести операций,
  которые раунд включает по умолчанию;
- `round_policy.py` — политика раунда: какие операции доступны, какие параметры видимы
  (не более двух на операцию) и какие значения закреплены сервером;
- `rules.py` — валидация цепочки и расчет ресурсов, лимитов и цели;
- `presentation.py` — разбор одного шага в набор подписанных параметров для admin-панели;
- `action_parameters.py`, `channels.py`, `scoring.py` — справочники и формулы.

Домен — единственный источник чисел: preview в UI и снимок при сохранении проходят через
один и тот же код.

### `schemas/`

Pydantic DTO по функциональным областям: `auth.py`, `rounds.py`, `scenarios.py`,
`leaderboard.py`, `errors.py`. Эти классы описывают API и не являются SQLAlchemy
моделями.

### `services/`

Основная логика: `auth.py`, `rounds.py`, `scenarios.py`, `scoring.py`,
`leaderboard.py`. Здесь находятся use cases, проверки переходов состояния, игровые
формулы и координация транзакций.

Если `scoring.py` или другой модуль вырастет, его можно позже превратить в подкаталог.
До этого момента дополнительный слой `domain/application` не нужен.

### `db/`

`session.py` создает SQLAlchemy sessions, `models/` содержит ORM-модели,
`repositories/` — SQL-запросы и блокировки. Миграции остаются в корневом
`migrations/`, потому что запускаются отдельной Alembic-командой.

### `ui/`

В `participant/app.py` и `admin/app.py` находятся точки запуска Streamlit. Страницы и
компоненты сначала можно держать рядом с приложением и выносить в подкаталоги только
после роста. `ui/shared/` содержит typed API client, cookie adapter и работу с
`st.session_state`.

`ui/shared/theme.py` реализует переключатель темной и светлой темы поверх серверной
темы Streamlit, `ui/shared/browser_meta.py` пересылает браузерные `User-Agent`,
`Accept-Language` и адрес клиента в API, `ui/admin/config_editor.py` — структурный
редактор конфигурации раунда.

UI не обращается к `db/` напрямую и не сохраняет каноническое состояние локально.

## Простые правила зависимостей

```text
Streamlit UI -> FastAPI API -> services -> db
                  │             │
                  └-> schemas <-┘
```

1. Браузер не вызывает FastAPI или PostgreSQL напрямую.
2. UI работает только через общий API client.
3. Router не содержит SQL и игровых формул.
4. `services/` владеет бизнес-решениями.
5. `db/` отвечает только за хранение и выборку.
6. DTO из `schemas/` отделены от SQLAlchemy models.
7. `mvp/` не импортируется production-кодом.

## Ориентировочные файлы первой версии

```text
src/aml_workshop_simulator/
├── api/
│   ├── main.py
│   ├── deps.py
│   ├── middleware.py
│   └── routers/
│       ├── auth.py
│       ├── rounds.py
│       ├── health.py
│       └── admin/
│           ├── rounds.py          # жизненный цикл и конфигурация
│           ├── presets.py         # пресеты настроек
│           ├── participants.py    # участники, версии, сессии
│           ├── leaderboard.py
│           ├── audit.py
│           └── common.py
├── core/
│   ├── config.py
│   ├── security.py
│   └── logging.py
├── schemas/
│   ├── auth.py
│   ├── rounds.py
│   ├── scenarios.py
│   ├── leaderboard.py
│   └── errors.py
├── domain/
│   ├── catalog.py
│   ├── round_policy.py
│   ├── rules.py
│   ├── presentation.py
│   └── scoring.py
├── services/
│   ├── scenario_service.py
│   ├── scenario_versions.py
│   ├── scoring_service.py
│   └── leaderboard_service.py
├── db/
│   ├── session.py
│   ├── models/
│   │   ├── users.py
│   │   ├── rounds.py
│   │   ├── scenarios.py
│   │   └── results.py
│   └── repositories/
│       ├── users.py
│       ├── rounds.py
│       └── scenarios.py
└── ui/
    ├── shared/
    │   ├── api_client.py
    │   ├── browser_meta.py
    │   ├── session.py
    │   └── theme.py
    ├── participant/
    │   └── app.py
    └── admin/
        └── app.py
```

Это ориентир, а не требование заранее создать десятки пустых файлов. Новый файл
добавляется, когда появляется соответствующий код.
