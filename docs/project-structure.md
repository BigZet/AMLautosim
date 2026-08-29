# Структура production-проекта

Проект — модульный монолит без лишнего количества архитектурных слоев. Код разделен
по шести областям внутри одного Python-пакета.

```text
.
├── src/aml_workshop_simulator/
│   ├── api/                       # FastAPI, routers, dependencies, error envelope
│   ├── core/                      # настройки, безопасность, метаданные запроса
│   ├── schemas/                   # Pydantic request/response DTO
│   ├── domain/                    # правила игры, каталог, политика раунда
│   ├── services/                  # use cases поверх домена и БД
│   ├── db/                        # SQLAlchemy, repositories, DB session
│   └── ui/
│       ├── shared/                # API client, cookies, тема, браузерные заголовки
│       ├── participant/           # participant Streamlit
│       └── admin/                 # admin Streamlit
├── migrations/                    # Alembic environment и revisions
├── resources/                     # сгенерированные датасеты для обучения ML-модели
├── deploy/                        # Dockerfile общего образа приложения
├── scripts/                       # seed базы и генерация датасетов
├── tests/                         # unit, contract, integration, ui, e2e
└── docs/
```

## Где что хранить

### `api/`

HTTP-слой FastAPI. В `main.py` создается приложение, регистрируются correlation
middleware и обработчики ошибок в общем envelope; `errors.py` описывает `ApiError`,
`deps.py` предоставляет текущую сессию и RBAC.

Routers: `auth.py`, `rounds.py` (участник), `health.py` (`/health/live` и
`/health/ready`) и пакет `admin/` — `rounds.py` (жизненный цикл и конфигурация),
`presets.py`, `participants.py`, `leaderboard.py`, `audit.py`, `common.py`.

Router разбирает HTTP-запрос и вызывает service. SQL и игровые формулы в router не
помещаются.

### `core/`

Общие технические настройки: `config.py` (Pydantic Settings), `security.py`
(bcrypt-хеши и непрозрачные session ID), `enums.py`, `request_meta.py` (адрес клиента
и браузерные заголовки с учетом trusted proxies). Игровые лимиты сюда не относятся:
они являются частью versioned ruleset.

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

Pydantic DTO по функциональным областям: `auth.py`, `rounds.py`, `round_config.py`,
`scenarios.py`, `leaderboard.py`, `admin.py`, `common.py`. Эти классы описывают API и
не являются SQLAlchemy моделями.

### `services/`

Use cases поверх домена и БД: `scenario_service.py`, `scenario_versions.py` (история
черновиков), `scoring_service.py`, `leaderboard_service.py`, `audit.py`.
`catboost_features.py` извлекает признаки сценария для обучения внешней ML-модели и в
HTTP-контур не входит — его использует `scripts/generate_catboost_sample_data.py`.

### `db/`

`session.py` создает SQLAlchemy async engine и sessions, `models/` содержит ORM-модели
(`users`, `sessions`, `action_cards`, `rounds`, `round_presets`, `scenarios`,
`scenario_versions`, `scoring_results`, `leaderboard_adjustments`, `audit_events`),
`repositories/` — SQL-запросы и блокировки. Миграции остаются в корневом
`migrations/`, потому что запускаются отдельной Alembic-командой.

### `ui/`

В `participant/app.py` и `admin/app.py` находятся точки запуска Streamlit.
`ui/shared/` содержит typed API client, cookie adapter и работу с `st.session_state`:
`api_client.py`, `session.py`, `theme.py` (переключатель темной и светлой темы поверх
серверной темы Streamlit), `browser_meta.py` (пересылка `User-Agent`,
`Accept-Language` и адреса клиента в API). `ui/admin/config_editor.py` — структурный
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

Новый файл добавляется, когда появляется соответствующий код: заранее создавать
пустые модули под будущие слои не нужно.
