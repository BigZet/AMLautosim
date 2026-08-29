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

**Причины.** Browser session ID не дает браузеру прямой маршрут к FastAPI, CORS не нужен, API attack surface
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

## D13. Email/password и server-side sessions в PostgreSQL

**Решение.** Participant регистрируется по email/password; password hash хранится в DB.
После login FastAPI создает server-side session, а Streamlit сохраняет непрозрачный ID в
route-scoped session cookie (`/play` или `/admin`) через `streamlit-cookies-controller`. В БД хранится только SHA-256 ID.

**Причины.** Cookie восстанавливает вход после потери Streamlit WebSocket/session;
server-side row дает немедленный revoke, аудит и простую проверку роли без self-contained claims.

**Последствия.** Компонентная cookie не может быть `HttpOnly`: обязательны HTTPS,
Secure, SameSite=Strict, XSS-защита и короткий lifetime. Появляются таблица `sessions`,
cleanup job и session lookup на каждом защищенном request.

**Пересмотреть, если:** требуется `HttpOnly`, SSO или event-code anonymous identity. Для
`HttpOnly` cookie должен выставлять HTTP BFF/proxy, а не JS-компонент.

## D14. Block state проверяется на каждом API request

**Решение.** FastAPI проверяет session row и актуальный `users.is_blocked` на каждом
защищенном request. Block/password reset в одной транзакции отзывают все active sessions.

**Причины.** Admin должен немедленно прекратить уже активную participant session.

**Последствия.** Protected request делает indexed session+user lookup; `last_seen_at`
обновляется с throttling. Оптимизация не должна вводить опасный shared auth cache.

**Пересмотреть, если:** вводится централизованный session cache с теми же revoke и
consistency guarantees.

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

Active round/cards читаются auth-free только во внутренней app network. Это исключает
session ID из process-wide cache; Streamlit по-прежнему требует login перед gameplay.

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

## D21. Раунд решает, какие операции и параметры видит участник

**Решение.** Конструктор по умолчанию предлагает шесть операций (`salary`,
`cash_deposit`, `card_transfer`, `international`, `cash_withdrawal`,
`crypto_exchange`), и у каждой не более двух настраиваемых параметров, включая канал.
Остальные параметры сервер закрепляет значениями по умолчанию. Ни одна карточка не
удаляется из каталога: доступность решает блок `operations` в снимке конкретного раунда,
а конфигурация без этого блока считается legacy и открывает все восемь карточек.

**Причины.** Универсальная матрица контекста перегружала интерфейс и делала выбор
неинформативным. Исключена связка `online_purchase` + `refund`: она добавляет отдельную
механику предусловия («возврат возможен только после покупки»), которая усложняет
конструктор сильнее всех остальных карточек вместе взятых. Проверено, что цель раунда
в 150 000 ₽ достижима без неё, а каждый лимит и квота по-прежнему имеют операцию,
способную их нарушить, — иначе часть правил стала бы недоказуемой.

**Последствия.** Скрытые параметры обязаны иметь стабильные серверные значения, иначе
скоринг перестанет быть детерминированным. Старые черновики и раунды продолжают
открываться и считаться. Клиент, приславший скрытый или чужой параметр, получает `422`
с конкретной причиной, а не молчаливое игнорирование.

**Пересмотреть, если:** методисту нужна другая глубина настройки, появляется механика,
требующая третьего параметра, или связка покупка/возврат возвращается как отдельный
режим раунда.

## D22. Мгновенный пересчет ресурсов делает сервер, а не UI

**Решение.** Предпросмотр ресурсов выполняется вызовом
`POST /rounds/{id}/scenario/preview`, который проходит тем же кодом, что и сохранение,
но ничего не пишет.

**Причины.** Вторая реализация правил в Streamlit неизбежно разошлась бы с серверной, и
участник видел бы одни числа при редактировании и другие после сохранения. Совпадение
должно быть свойством архитектуры, а не дисциплины.

**Последствия.** Каждая правка шага — это HTTP-запрос, поэтому ответы кэшируются по
содержимому цепочки. UI больше не содержит игровых констант: лимит операций, цель и
стартовые ресурсы приходят из снимка раунда.

**Пересмотреть, если:** задержка сети станет заметной на площадке; тогда допустим
локальный кэш ответов, но не локальный расчет.

## D23. История черновиков — append-only, восстановление создает новую версию

**Решение.** Каждое явное сохранение добавляет строку в `scenario_versions`.
Восстановление старой версии создает новую с её содержимым; более поздние версии
остаются. Отправка фиксирует ровно одну версию, и скоринг читает именно её.

**Причины.** Участник должен иметь право на эксперимент без страха потерять сделанное, а
организатор — видеть, как менялось решение. Откат с удалением новых версий превратил бы
«вернуться и посмотреть» в разрушающую операцию.

**Последствия.** Объем данных растет линейно по числу сохранений; это осознанная цена.
История хранится в PostgreSQL, а не в `st.session_state`, поэтому переживает
перезапуск процессов и видна администратору.

**Пересмотреть, если:** число версий на участника станет неограниченным; тогда вводится
лимит или сворачивание истории, но не молчаливая перезапись.

## D24. Остановка и перезапуск раунда вместо «начать заново»

**Решение.** Жизненный цикл включает `stopped`; перезапуск создает новый раунд с копией
конфигурации и ссылкой `restarted_from_round_id`, а прежний останавливает.

**Причины.** Ведущему нужен способ прервать игру и начать чистый прогон, не потеряв
данные предыдущего. Любая операция «сбросить раунд», удаляющая сценарии, необратима на
мероприятии и не подлежит разбору постфактум.

**Последствия.** Инвариант «не более одного идущего раунда» держит частичный уникальный
индекс, команды сериализуются блокировкой строки, повторный запрос возвращает уже
созданную замену. Список раундов растет — это нормальный журнал мероприятия.

**Пересмотреть, если:** понадобятся параллельные раунды для нескольких групп; это
меняет инвариант единственного активного раунда и требует отдельного решения.

## D25. Публичный лидерборд обезличен по умолчанию

**Решение.** Публичная проекция возвращает `Игрок #N` и `masked: true`; настоящий ник
выдается только по явному запросу `?reveal=true`, который UI отправляет после нажатия
кнопки.

**Причины.** Лидерборд показывают на проекторе, а ник участник выбирает сам. Скрытие
только в разметке не защищает: имя уже было бы в DOM и в ответе API.

**Последствия.** Маскирование выполняется на сервере до сериализации. Admin-борд и поиск
участников продолжают показывать настоящие данные — это разные аудитории.

**Пересмотреть, если:** организатор захочет постоянное раскрытие для внутренних
мероприятий; тогда это становится параметром раунда, а не значением по умолчанию.

## D26. Светлая тема — per-browser overlay поверх серверной темы

**Решение.** Streamlit отдает одну серверную тему; светлый режим реализован
переопределением CSS-переменных и явной перекраской виджетов, выбор хранится в cookie
`aml_theme`, стартовая тема — темная.

**Причины.** Серверная тема одна на все браузеры, поэтому «переключатель» на её основе
менял бы оформление всем участникам сразу.

**Последствия.** Каждый новый виджет, у которого цвет приходит из серверной темы,
приходится перекрашивать явно; это проверяется браузерными тестами на контраст и
отсутствие обрезанного текста в обеих темах.

**Пересмотреть, если:** Streamlit добавит поддержку темы на уровне сессии — тогда
overlay заменяется штатным механизмом.

## D27. Адресу из `X-Forwarded-For` верят только доверенные прокси

**Решение.** Клиентский адрес берется из сокета; `X-Forwarded-For` учитывается, только
если непосредственный клиент перечислен в `TRUSTED_PROXY_IPS`. По умолчанию список пуст.

**Причины.** Заголовок подделывается тривиально. Без явного списка доверенных прокси
любой участник мог бы записать в журнал чужой адрес.

**Последствия.** В compose-развертывании без настройки в журнале виден адрес контейнера
UI. Чтобы видеть адрес браузера, организатор явно перечисляет сеть UI-контейнеров.
Streamlit пересылает браузерные `User-Agent` и `Accept-Language`, но решение о доверии
принимает API.

**Пересмотреть, если:** появится внешний reverse proxy или CDN; список пополняется
осознанно, вместе с проверкой, что заголовок перезаписывается на границе.
