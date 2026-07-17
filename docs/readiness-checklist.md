# Матрица готовности целевой архитектуры

Дата актуализации определяется последним commit документации. Статусы относятся к
реализации, а не к полноте архитектурного описания.

Обозначения:

- **Реализовано** — основа уже есть и соответствует направлению v1.
- **Изменить** — код существует, но контракт или ответственность не соответствует цели.
- **Добавить** — обязательного компонента пока нет.

## Уже реализовано

| Возможность | Текущее подтверждение | Ограничение | Проверка |
| --- | --- | --- | --- |
| Каркас FastAPI | `backend/app/main.py`, routers | Нет `/api/v1`, единого error envelope и request ID | OpenAPI и API tests |
| SQLAlchemy и PostgreSQL | session, entities, PostgreSQL 16 в compose | Схема упрощена, нет Alembic | Integration test с PG |
| Регистрация и вход | auth router, bcrypt, JWT, роли | Нет lockout и production bootstrap admin | Auth tests |
| Базовые раунды | create/list/activate, статусы | Нет config snapshot и блокировок | State transition tests |
| Сценарии | submit/mine/result, unique participant+round | Нет server-side draft API и расширенных правил | Scenario integration tests |
| Синхронный scoring | scoring service и admin endpoint | Используются упрощенные признаки и float | Determinism/unit tests |
| Admin Streamlit | login, раунды, scoring, stats, board | Старые пути и минимальная конфигурация | UI smoke test |
| Participant UX | Конструктор, деньги, энергия, комиссии | Работает через `LocalStore`, не через API | Ручной smoke текущего прототипа |
| Архитектурное описание | Документы в `docs/` | Реализация еще должна пройти миграцию | Проверка ссылок и терминов |

## Требуется изменить

| Изменение | Целевое состояние | Основные области | Критерий приемки |
| --- | --- | --- | --- |
| Версионирование API | Все прикладные пути под `/api/v1` | FastAPI routers, API client | Contract tests проходят по документу API |
| Модель карточек | Версия, flow, энергия, комиссия, суммы, частота, prerequisite | entities, schemas, seed | Карточки раунда полностью приходят из PG |
| Конфигурация раунда | Неизменяемый `game_config` snapshot | Round model/service | После activate PUT дает `409` |
| Игровые правила | Единственная реализация в backend | `local_store.py` → game rules service | Backend повторяет все resource tests |
| Сценарии | GET/PUT draft, submit, revision, server preview | schemas, scenario service/router | Черновик восстанавливается после перезапуска UI |
| Пакетный scoring | Decimal, scoring version, row lock, атомарность | rounds/scoring services | Нет частичной доски при исключении |
| Participant Streamlit | Только API, JWT/session UI state | participant app, API client | В коде нет `LocalStore` |
| Admin Streamlit | Конфиг раунда, новые stats/status/error flow | admin app, API client | Полный раунд без терминала |
| Кэширование | Resource HTTP client; data только round/cards | Streamlit client/apps | Нет user-specific cached functions |
| Health | `/health/live` и `/health/ready` | FastAPI main/db | Ready падает при недоступной БД |
| Аутентификация | Account lockout и безопасный bootstrap admin | user model, auth service | 5 ошибок блокируют вход на 5 минут |
| Compose | Полный набор сервисов и закрытые порты | `docker-compose.yml` | Снаружи видны только 80/443 |

## Требуется добавить

| Компонент | Назначение | Критерий приемки |
| --- | --- | --- |
| Alembic | Управляемые миграции схемы | Чистая и существующая dev-БД достигают `head` |
| Dockerfile | Неизменяемый образ API и Streamlit | Образ собирается без локального Python environment |
| Reverse proxy | TLS, маршруты, WebSocket, headers | `/play` и `/admin` работают по HTTPS |
| Разделенные Docker-сети | Изоляция API и PostgreSQL | 8000/5432 недоступны извне |
| Request ID middleware | Корреляция UI/API/ошибок | Каждый ответ и log event содержит ID |
| Structured logging | Диагностика без PII | Проверка логов не находит email/JWT/body |
| Метрики/операторский dashboard | Нагрузка, ошибки, scoring duration | Оператор видит сигналы из `operations.md` |
| Backup/restore automation | Восстановление PostgreSQL | Restore drill выполнен до события |
| Error envelope | Стабильные ошибки UI | Все 4xx/5xx соответствуют единой схеме |
| Интеграционные тесты PG | Транзакции, locks, constraints | Тесты проходят на PostgreSQL 16 |
| End-to-end UI тесты | Participant и admin flow | Полный раунд проходит автоматически |
| Нагрузочный тест | Подтверждение 500 участников | p95 < 500 мс, error < 1%, score < 10 с |
| Security tests | RBAC, IDOR, JWT, закрытые endpoints | Выполнен checklist `security.md` |

## Приемочный end-to-end сценарий

1. На чистой БД выполнить миграции и bootstrap администратора.
2. Создать `draft` с 250 000 ₽, 14 энергии, 8 действиями и целью 150 000 ₽.
3. Активировать раунд и подтвердить неизменяемость конфигурации.
4. Зарегистрировать двух участников; проверить уникальность email и role isolation.
5. Сохранить черновик, перезапустить participant UI, войти и восстановить его.
6. Отклонить сценарии с отрицательным балансом, нехваткой энергии и неверным возвратом.
7. Отправить валидные сценарии и повторно отправить измененную ревизию до scoring.
8. Запустить scoring, проверить блокировку параллельного запуска и атомарный commit.
9. Сверить собственный result и обезличенную admin board.
10. Перезапустить сервисы и подтвердить сохранность данных.
11. Создать backup и восстановить его в отдельную БД.

## Команды проверки документации

После изменения архитектурного пакета выполняются:

```powershell
rg -n "^```mermaid|^# |^## " docs
rg -n "LocalStore|/api/v1|draft|active|scoring|completed" docs
git diff --check
```

Дополнительно проверяются относительные Markdown-ссылки, парность code fences и
рендеринг всех Mermaid-диаграмм в поддерживаемом Markdown viewer или Mermaid CLI.

## Условие готовности к мероприятию

Система готова только когда все строки раздела «Требуется изменить» переведены в
реализованные, обязательные строки «Требуется добавить» имеют подтвержденную проверку,
а end-to-end, load, security и restore сценарии пройдены на release image и целевой VM.

