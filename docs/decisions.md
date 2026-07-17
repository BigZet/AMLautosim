# Архитектурные решения

Документ использует формат ADR-lite: решение, причины, последствия и условия
пересмотра. Все решения имеют статус **принято для v1**, пока явно не заменены новым
пунктом. Изменение требует синхронного обновления связанных docs, contracts и readiness.

## D1. Одна облачная VM

**Решение.** Reverse proxy, два Streamlit, FastAPI и PostgreSQL работают на одной VM.

**Причины.** Один 45-минутный event, до 500 users, простая поддержка и быстрый recovery
важнее высокой инфраструктурной сложности.

**Последствия.** VM является single failure domain; нужны preflight, headroom, backup и
reserve workshop flow. Vertical scaling выполняется первым.

**Пересмотреть, если:** несколько мероприятий, HA/SLA, независимый DB lifecycle или VM
не выдерживает accepted load profile.

## D2. Docker Compose вместо Kubernetes

**Решение.** V1 развертывается pinned Docker Compose с edge/app/data networks.

**Причины.** Один host не оправдывает orchestrator; Compose дает воспроизводимые
commands, service isolation и image rollback.

**Последствия.** Нет автоматического rescheduling/HA; operator runbook обязателен.

**Пересмотреть, если:** несколько nodes, platform requirement, autoscaling или shared
organization cluster.

## D3. Streamlit — server-side UI, FastAPI — внутренний application API

**Решение.** Browser обращается только к Streamlit. Python-процесс Streamlit вызывает
FastAPI по внутренней Docker-сети.

**Причины.** Bearer JWT не попадает в browser storage, CORS не нужен, API attack surface
меньше, UI остается быстрым для прототипирования мастер-класса.

**Последствия.** Streamlit sessions связаны с WebSocket/process; при масштабировании
нужны sticky sessions. API contract остается полноценным и версионированным.

**Пересмотреть, если:** появляется mobile/SPA/external client или public API. Тогда
нужны gateway, browser auth/CORS/CSRF model и отдельная public security review.

## D4. Два отдельных Streamlit-приложения

**Решение.** Participant и admin UI запускаются отдельными processes/containers.

**Причины.** Разная аудитория, navigation, security posture и capacity; admin failure не
должен требовать restart participant UI.

**Последствия.** Они не разделяют `session_state`/cache и получают общие данные только
через API. Current MVP independent in-memory state допустим как UI-reference, не target.

**Пересмотреть, если:** общий design system становится отдельным package; это не требует
объединять runtime processes.

## D5. PostgreSQL — единственный persistent source of truth

**Решение.** Accounts, rounds, cards, drafts, scenarios, results, adjustments и audit
хранятся в PostgreSQL.

**Причины.** State переживает rerun/restart; transactions, constraints и locks решают
гонки и atomic publication.

**Последствия.** Недоступность DB запрещает запись; LocalStore fallback отсутствует.

**Пересмотреть, если:** роль PostgreSQL не пересматривается. Можно менять hosting или
добавлять read/cache layers, но они не становятся владельцами данных.

## D6. FastAPI является единственным владельцем бизнес-правил

**Решение.** Validation, resources, state transitions, scoring, explanation, ranking и
admin mutation semantics выполняются в FastAPI/domain layer.

**Причины.** Один канонический результат для двух UI, воспроизводимость и security.

**Последствия.** Streamlit preview допускается только как UX optimization и всегда
заменяется server response.

**Пересмотреть, если:** никогда в пользу доверия клиентскому расчету. Domain package
может переехать в отдельный service без изменения ответственности.

## D7. Версионированный внутренний API `/api/v1`

**Решение.** Все прикладные маршруты имеют version prefix и единый error envelope.

**Причины.** Participant/admin развиваются независимо от backend deploy; внутренний API
тоже требует contract stability и тестируемого migration path.

**Последствия.** Breaking change требует совместимого окна или `/api/v2`. Health routes
не versioned.

**Пересмотреть, если:** не требуется; конкретная версия меняется, принцип остается.

## D8. DTO отделены от ORM/domain implementation

**Решение.** Pydantic contracts находятся в узком shared-contract layer либо генерируются
из OpenAPI; Streamlit не импортирует ORM, repositories или application services.

**Причины.** Снижает schema drift без нарушения границы. DTO могут использоваться
ApiClient и FastAPI, но не содержат бизнес-формул.

**Последствия.** Dependency rules проверяются тестом/import lint. ORM entity не является
response model.

**Пересмотреть, если:** generated client полностью заменит shared Python models.

## D9. Optimistic concurrency для UI-редактирования

**Решение.** Scenario использует `expected_revision + client_mutation_id`; round config,
access state и adjustment имеют свои expected versions.

**Причины.** Streamlit rerun, timeout и два окна не должны терять изменения или
дублировать команды.

**Последствия.** UI обязан обрабатывать `409`, хранить pending command и не использовать
silent last-write-wins.

**Пересмотреть, если:** collaborative real-time editor потребует event/CRDT model.

## D10. Динамические формы карточек декларативны

**Решение.** Card version хранит безопасную field specification; Streamlit строит форму
по ней. Executable effects живут в versioned server ruleset registry.

**Причины.** Разные действия требуют разных параметров, но хранить/eval исполняемую
логику в JSON небезопасно и трудно тестировать.

**Последствия.** Card schema и ruleset version должны быть совместимы и проверяются при
activate. Старые implementations сохраняются на retention period.

**Пересмотреть, если:** появляется полноценный audited rules DSL с parser/sandbox.

## D11. Immutable card versions и round snapshot

**Решение.** Published card semantics меняются новой version; active round хранит
card refs, resources, constraints и versions всех engines.

**Причины.** Один scenario должен воспроизводиться после изменения catalog/release.

**Последствия.** Active config не редактируется; old rulesets нельзя удалить слишком
рано.

**Пересмотреть, если:** cards получают отдельный publication workflow; тогда добавляется
normalized round-card mapping, но snapshot principle сохраняется.

## D12. Синхронный атомарный batch scoring

**Решение.** Admin POST удерживает request, берет round row lock NOWAIT и в одной
PostgreSQL transaction рассчитывает/публикует все submitted results.

**Причины.** До 500x8 steps и легкий ruleset укладываются в target <10 s; очередь
добавила бы state и operational complexity.

**Последствия.** Transaction дольше обычной; score имеет 30 s timeout, benchmark gate и
read-back flow при неопределенном ответе. Crash приводит к rollback.

**Пересмотреть, если:** scoring >10 s, тяжелая ML model, progress/retry jobs, несколько
rounds или transaction pressure. Тогда вводится job resource + queue/worker.

## D13. Email/password и event-lifetime JWT

**Решение.** Participant регистрируется по email/password; bcrypt hash в DB; JWT default
4 часа хранится в `st.session_state`.

**Причины.** Повторный login восстанавливает draft после потери UI session; current
backend уже использует эту модель.

**Последствия.** Требуются data notice/retention, password policy, lockout и deletion.
Refresh token v1 отсутствует.

**Пересмотреть, если:** организатор запрещает email, доступен SSO или event code +
anonymous identity. Это требует privacy и account-recovery redesign.

## D14. Block state проверяется на каждом API request

**Решение.** FastAPI сверяет DB `is_blocked` и `token_version`, а не доверяет только JWT.

**Причины.** Admin должен немедленно прекратить уже активную participant session.

**Последствия.** Protected request делает user lookup; его оптимизация не должна вводить
опасный shared cache. Block increment revokes old tokens.

**Пересмотреть, если:** вводится short-lived token + centralized revocation/cache с теми
же security guarantees.

## D15. Game score объединяет риск и ресурсы

**Решение.** Референс `leaderboard-v1`: 60% stealth (`100-risk`) и 40% resource score;
resource score учитывает balance/energy/time/trust/fees/slots.

**Причины.** Победа только по classifier score поощряет неэффективные/тривиальные
сценарии; ресурсы создают содержательный trade-off.

**Последствия.** Formula/weights snapshot-ятся; значения round-configurable, не constants.

**Пересмотреть, если:** методика мастер-класса меняет objective/метрики. Нужна новая
`leaderboard_version`, а не silent formula change.

## D16. Ручная корректировка — overlay, не изменение model result

**Решение.** Admin может менять effective leaderboard values через отдельную таблицу с
reason/revision/audit. Base scoring result immutable.

**Причины.** Организатору нужен инструмент исправления демонстрационной ошибки, но
воспроизводимость и прозрачность важнее удобства прямого overwrite.

**Последствия.** UI показывает base/effective и adjustment marker; clear возвращает base.

**Пересмотреть, если:** корректировки запрещены policy. Тогда endpoints/UI отключаются,
но base model остается неизменяемой.

## D17. Контролируемое кэширование Streamlit

**Решение.** `st.cache_resource` только HTTP transport; `st.cache_data` только active
round/cards/static dictionaries. User/admin mutable data не cached globally.

**Причины.** Streamlit cache process-wide и может смешать sessions; небольшой read cache
нужен только immutable/short-lived data.

**Последствия.** Stats/leaderboard/profile/result идут в API; admin commands явно clear
только локальный admin cache после success. Отдельный participant process видит изменения
по active-round TTL и новому config-version key.

Active round/cards читаются token-free только во внутренней app network. Это исключает
JWT из process-wide cache; Streamlit по-прежнему требует login перед gameplay.

**Пересмотреть, если:** внешний shared cache добавляется по измерениям. Security/data
ownership rules сохраняются.

## D18. Один active/scoring round без неявного завершения

**Решение.** Partial unique index допускает один `active` или `scoring`. Activate нового
при конфликте возвращает `409`, не меняя прежний round.

**Причины.** Неявное завершение может потерять submissions и запутать participant UI.

**Последствия.** Operator/admin должны завершить текущий workshop flow до нового round.

**Пересмотреть, если:** несколько залов/events. Нужны event/tenant scope и явная привязка
participant к round.

## D19. Без Redis, Celery и offline fallback в v1

**Решение.** Нет distributed cache, task queue и автоматического LocalStore.

**Причины.** Каждый компонент добавляет mutable state/monitoring/failure modes без
измеренной необходимости. Fallback создает split-brain.

**Последствия.** DB/API outage временно останавливает writes; workshop имеет content
fallback, а не data fallback.

**Пересмотреть, если:** несколько VM требуют shared limiter/cache; scoring требует job
queue. Offline mode возможен только отдельным продуктом с явным export/import protocol.

## D20. Data minimization и ограниченный retention

**Решение.** Собирать email, pseudonym и game state; рекомендуемый retention не более
30 дней, включая backup.

**Причины.** Аудитория включает школьников; долгосрочное хранение не нужно цели workshop.

**Последствия.** Нужны notice, owner, deletion procedure и безопасные aggregates.

**Пересмотреть, если:** legal/organizational basis требует иной срок. Решение оформляется
до сбора данных и отражается в UI/policy/runbook.
