# Безопасность

## 1. Контекст

Система учебная, но обрабатывает учетные данные и поведение школьников. Упрощенный
scoring не уменьшает требования к защите email, пароля, session ID, admin-команд и базы.

Основные активы:

- учетные записи и email;
- participant/admin browser cookie и server-side sessions;
- scenario chains и explanations;
- immutable round/scoring configuration;
- base results, leaderboard overlays и audit events;
- PostgreSQL volume, backup и production secrets;
- доступность интерфейса в течение 45 минут.

## 2. Доверительные границы

```mermaid
flowchart LR
    subgraph untrusted["Недоверенная зона"]
        player["Participant browser"]
        adminBrowser["Admin browser"]
        internet["Internet and venue Wi-Fi"]
    end

    subgraph edge["Публичная граница VM"]
        proxy["Reverse proxy and TLS"]
        participantUi["Participant Streamlit"]
        adminUi["Admin Streamlit"]
    end

    subgraph app["Внутренняя application network"]
        api["FastAPI"]
    end

    subgraph data["Внутренняя data network"]
        db[("PostgreSQL")]
        volume[("Persistent volume")]
    end

    player --> internet -->|"HTTPS and WebSocket"| proxy
    adminBrowser --> internet
    proxy --> participantUi
    proxy --> adminUi
    participantUi -->|"Internal HTTP plus X-Session-ID"| api
    adminUi -->|"Internal HTTP plus X-Session-ID"| api
    api -->|"Least-privilege DB account"| db
    db --> volume
    operator["Authorized operator"] -->|"SSH key or VPN"| edge
    operator --> app
    operator --> data
```

### Ключевое следствие

Browser хранит отдельные `aml_play_session_id` (`Path=/play`) и `aml_admin_session_id` (`Path=/admin`), созданные JavaScript-компонентом
`streamlit-cookies-controller`; FastAPI и PostgreSQL владеют server-side сессией.
Браузер не имеет route к FastAPI, но cookie доступна JavaScript и не может быть
`HttpOnly`. Поэтому XSS рассматривается как путь к краже сессии, а `Secure`,
`SameSite=Strict`, host-only scope, HTTPS и короткий lifetime обязательны.

## 3. Threat matrix

| Угроза | Актив | Мера v1 | Проверка |
| --- | --- | --- | --- |
| Подбор пароля | Accounts | Password policy, bcrypt, lockout, auth rate limit | Auth security tests |
| Кража UI session | Participant/admin access | HTTPS, Secure + SameSite=Strict cookie, XSRF/XSS protection, short lifetime, server revoke | Browser/proxy tests |
| Participant вызывает admin API | Results/config | Session lookup + DB role check on every request | RBAC matrix |
| IDOR | чужой scenario/profile | Ownership derived from server-side session; admin routes isolated | IDOR tests |
| Подмена active config | Reproducibility | Immutable snapshot/hash and state transition lock | Integration tests |
| Lost update | Scenario/admin overlay | Revisions, mutation IDs, row locks | Concurrency tests |
| Повтор score | Round/result | Idempotency key, `FOR UPDATE NOWAIT`, completed summary | Concurrency tests |
| Утечка через logs | Email/session ID/steps | Structured allowlist logging and redaction | Automated log scan |
| Публикация DB/API | All data | No host ports, firewall, internal networks | External port scan |
| XSS через display name/details | Admin/public UI | Output escaping, no unsafe HTML with user input | UI security tests |
| SQL injection | DB | SQLAlchemy bound parameters, strict DTO | Fuzz/security tests |
| DoS с общего NAT | Availability | Body/connection limits, NAT-aware burst, capacity test | Venue load test |
| Компрометация dependency/image | Runtime | Pinned lock, image scan, minimal image, provenance | CI release gate |
| Утечка backup | Historical PII | Encryption, restricted storage, retention/restore process | Backup audit |

## 4. Пароли и аутентификация

- Password: 10–128 символов; пробелы не обрезаются без явно описанного правила.
- В v1 используется bcrypt с cost, измеренным на production VM: проверка должна быть
  достаточно дорогой, но не создавать auth DoS для 500 участников.
- Hash и salt управляются библиотекой; собственная криптография запрещена.
- Пароль существует в Streamlit только во время form submit и не сохраняется в
  `session_state`, cache, URL или log.
- Login response для неизвестного email и неверного password одинаков.
- После пяти неудачных попыток account временно блокируется на пять минут; значения
  являются настраиваемой security policy.
- Успешный login сбрасывает failed counter в транзакции.
- Admin account создается bootstrap-командой; публичная регистрация всегда participant.
- Default admin credentials запрещены вне локальной demo-среды.

Argon2id может заменить bcrypt отдельным решением с постепенным rehash при login; формат
`hashed_password` не должен связывать API contract с конкретным алгоритмом.

## 5. Server-side сессия и жизненный цикл

Полная спецификация: [Browser cookie и серверные сессии](sessions-and-cookies.md).

- FastAPI генерирует 32 случайных байта CSPRNG и возвращает raw `session_id` только в
  login response.
- PostgreSQL хранит только SHA-256 hash, user ID, created/expiry/last-seen/revoke
  metadata.
- Default lifetime — 4 часа, без refresh/sliding expiration в v1.
- Session fixation запрещен: login всегда создает новый ID.
- Logout отзывает текущую строку; block и password reset атомарно отзывают все активные
  сессии пользователя.
- `last_seen_at` обновляется с throttling, а не на каждом GET.

```mermaid
sequenceDiagram
    participant S as Streamlit
    participant A as FastAPI
    participant D as PostgreSQL

    S->>A: Request with X-Session-ID
    A->>A: Validate format and hash raw ID
    A->>D: Load session and user
    alt active session and account
        A-->>S: Authorized response
    else expired or revoked
        A-->>S: 401 session_expired or session_revoked
    else user blocked
        A-->>S: 403 account_blocked
    end
```

## 6. Browser cookie и Streamlit security

- `server.enableXsrfProtection=true` в production.
- `CookieController` создается со стабильным key; `None` до hydration не считается
  logout.
- Cookie: route-specific name/path, `Secure=true`, `SameSite=Strict`, host-only,
  expiry не позже server-side сессии.
- `HttpOnly` недоступен, поскольку компонент использует JavaScript/universal-cookie.
- Session ID/cookie map не помещаются в `st.cache_data`, query params или widget keys.
- Cached HTTP transport не содержит mutable default `X-Session-ID` header.
- User-controlled text экранируется перед `unsafe_allow_html=True`; предпочтителен
  native Streamlit rendering.
- Admin destructive actions требуют explicit confirmation и reason.
- После logout удаляется cookie с идентичным scope и очищаются auth, local draft,
  selected participant и pending command.
- WebSocket origin/CORS settings ограничены каноническим доменом.

## 7. Авторизация

### Participant

- Current participant определяется только `sessions.user_id` после проверки `X-Session-ID`.
- Auth-free active-round/cards reads разрешены только во внутренней app network,
  содержат несекретный catalog snapshot и не проксируются browser.
- Endpoint scenario/result не принимает participant ID.
- Round ID проверяется на доступность и lifecycle.
- Public leaderboard возвращает только pseudonym и безопасные метрики.
- Blocked participant не может читать/изменять даже собственный scenario до unblock.

### Admin

- Все `/api/v1/admin/*` требуют current DB role `admin`.
- Admin не может заблокировать самого себя через UI/API.
- Block, adjustment, activate и score требуют reason/confirmation там, где определено.
- Изменение создает audit event в той же транзакции.
- Full email/chain читается только detail endpoint выбранного player.
- Admin UI рекомендуется дополнительно ограничить VPN/IP allowlist, если площадка это
  позволяет; URL secrecy не является защитой.

## 8. Сетевая защита

```mermaid
flowchart TB
    internet["Internet"] -->|"80 redirect and 443 HTTPS"| firewall["Cloud firewall"]
    firewall --> proxy["Reverse proxy"]
    proxy -->|"/play"| playerUi["Participant UI"]
    proxy -->|"/admin"| adminUi["Admin UI"]
    proxy -. "deny" .-> api["FastAPI 8000"]
    proxy -. "deny" .-> db["PostgreSQL 5432"]
    playerUi --> api
    adminUi --> api
    api --> db
```

- Публичны только 80/443; HTTP перенаправляется на HTTPS.
- TLS 1.2+; слабые suites отключены.
- HSTS включается после проверки домена и rollback plan.
- API/DB не имеют host port mappings.
- OpenAPI/Swagger не проксируются; внутри VM доступ ограничен оператором.
- SSH по ключу, без password login, с allowlist/VPN при возможности.
- DB user приложения не superuser и не владеет infrastructure DB.
- Backup channel отделен от public route.

Security headers: `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`,
`Referrer-Policy`, `Permissions-Policy` и CSP, протестированная с Streamlit WebSocket и
static assets. `X-Frame-Options`/`frame-ancestors` запрещает embedding, если iframe не
нужен платформе мероприятия.

## 9. Rate limiting и DoS

500 участников могут находиться за одним NAT, поэтому жесткий per-IP limit опасен.

| Уровень | Ограничение |
| --- | --- |
| Proxy | Max body, header size, connection timeout, WebSocket limits, broad IP burst |
| Auth API | Account-based lockout, route-wide rate, separate strict admin policy |
| Application | Max steps, string lengths, nested JSON depth, pagination limit |
| Database | Pool bounds, statement timeout, lock timeout |
| Scoring | Один batch, row lock NOWAIT, max scenarios/steps, 30 s request timeout |

Точные значения выбираются после теста через Wi-Fi площадки. Redis-less limiter v1
может быть process-local только как дополнительная защита; критическая защита основана
на proxy limits и DB/account state. При нескольких API replicas нужен общий limiter.

## 10. Валидация и целостность

- Pydantic input models используют `extra="forbid"`.
- Reverse proxy и API ограничивают body до размера, достаточного для max scenario.
- Decimal используется для всех денежных/score расчетов.
- Card ID/code/version сверяются с immutable round snapshot.
- Action details валидируются server registry, а не доверяются UI metadata.
- `step_id` UUID и array length проверяются.
- Server игнорирует клиентский resource preview.
- State transitions защищены row locks и DB constraints.
- SQLAlchemy использует bound parameters.
- URL IDs не считаются секретными; RBAC/ownership проверяется всегда.

## 11. Защита admin-команд

```mermaid
flowchart LR
    ui["Admin confirmation"] --> dto["Strict command DTO"]
    dto --> rbac["Current DB role"]
    rbac --> conflict["Expected access or aggregate revision"]
    conflict --> transaction["Mutation plus audit in one transaction"]
    transaction --> response["Canonical response"]
```

- `Idempotency-Key` обязателен для activate/score; хранится только его hash.
- Причина обязательна для block и leaderboard adjustment.
- Base scoring result immutable.
- UI показывает base/effective рядом, чтобы admin видел последствия.
- Audit event содержит numeric before/after, но не полную chain/PII.
- Опционально применяется dual control для финальных мероприятий; в v1 не требуется.

## 12. Секреты

Production secrets не входят в Git, Docker image, Markdown examples или application
logs.

| Secret | Потребитель | Ротация |
| --- | --- | --- |
| `DATABASE_URL`/password | FastAPI | До мероприятия или при инциденте |
| `POSTGRES_PASSWORD` | DB bootstrap/operator | По infrastructure policy |
| TLS private key | Reverse proxy | ACME/организатор |
| Backup credentials/key | Operator job | Отдельно от application secrets |
| Observability HMAC key | Logging pipeline | При компрометации |

`.env` на VM доступен только сервисному пользователю. Предпочтительны Docker secrets или
cloud secret store, если они доступны без существенного усложнения v1. Ошибка config не
должна печатать значение secret.

## 13. Logging и observability privacy

Логирование строится по allowlist.

**Разрешено:** service, event, route template, method, status, latency, request ID,
round ID, scenario ID, internal user ID, role, revisions, counts.

**Запрещено:**

- password/password hash;
- raw session ID, cookie, `X-Session-ID`, `sessions.session_id_hash`;
- email и display name в техническом log;
- request/response body auth/scenario;
- full steps/action details/explanation;
- DSN и secret values;
- raw idempotency key.

При необходимости поиска account используется HMAC(normalized email) с отдельным
observability key. Raw email остается доступен только через admin detail/API по RBAC.

## 13.1. Технические данные входа

Сессия хранит то, что нужно организатору для разбора инцидента, и ничего сверх этого:
`ip_address` (`INET`, IPv4 и IPv6), `user_agent`, `accept_language`, время создания,
последней активности, истечения и отзыва. Пароля, raw session ID и любых
fingerprinting-данных (canvas, шрифты, device hash) в базе нет.

Адрес берется из сокета. `X-Forwarded-For` учитывается **только** тогда, когда
непосредственный клиент перечислен в `TRUSTED_PROXY_IPS`; при пустой настройке (значение
по умолчанию) заголовок игнорируется полностью, поэтому участник не может продиктовать
серверу чужой адрес. Список задается CIDR-нотацией и должен содержать только сети, за
которые отвечает организатор.

Streamlit — самостоятельный HTTP-клиент, поэтому UI пересылает браузерные `User-Agent`,
`Accept-Language` и адрес клиента; решение «верить или нет» остается за API и тем же
правилом trusted proxies. Без этого в журнале был бы адрес контейнера UI и строка
`python-httpx/...` вместо реального браузера.

Смотреть эти поля может только администратор: participant API их не возвращает ни в
одном ответе, а попытка обратиться к admin-эндпоинту с participant-сессией — `403`.

## 13.2. Ники в лидерборде

Публичный лидерборд по умолчанию отдает `Игрок #N` и `masked: true`; настоящего
`display_name` нет ни в ответе API, ни в DOM страницы. Раскрытие — явное действие:
кнопка «Показать все ники» в UI и параметр `?reveal=true` у API. После перезагрузки
состояние снова безопасное.

Это защита от предсказуемой ситуации: лидерборд показывают на проекторе, а участник
может зарегистрироваться под провокационным ником. Admin-борд и поиск участников
продолжают показывать настоящие данные — требование касается публичных списков.

## 14. Минимизация данных школьников

1. Собирать только email, pseudonym/display name и игровое состояние.
2. До регистрации показать цель, владельца, срок и способ удаления.
3. Рекомендовать pseudonym, не ФИО, для public leaderboard.
4. Не показывать email на проекторе/общей доске; ники на общем экране скрыты по
   умолчанию и раскрываются только явной командой ведущего.
5. Не экспортировать chains без явной необходимости.
6. Установить retention до события; рекомендуемый максимум — 30 дней.
7. Удалить primary DB и backups по расписанию.
8. Хранить только действительно обезличенные агрегаты после проверки re-identification.

## 15. Backup security

- Dump шифруется до передачи во внешнее хранилище.
- Encryption key не хранится рядом с dump.
- Access ограничен назначенными операторами.
- Restore выполняется в изолированной test DB.
- Restore logs не содержат row data.
- Retention backup не превышает retention исходной PII.
- Удаление подтверждается inventory/checksum records.

## 16. Supply chain и runtime

- Python dependencies pin/lock с hashes, где возможно.
- Base image фиксируется digest/tag release.
- Image запускается непривилегированным user.
- Read-only filesystem для stateless containers при совместимости Streamlit temp paths.
- Linux capabilities минимизированы; Docker socket не монтируется в app containers.
- Dependency/image scan выполняется до release freeze.
- Critical vulnerability оценивается до мероприятия; исключение документируется.
- Debug/reload отключены в production.

## 17. Security checklist перед событием

1. Production secrets отличаются от dev и не найдены secret scan.
2. Default admin отсутствует; admin password проверен.
3. Снаружи закрыты 8000/5432 и OpenAPI endpoints.
4. TLS/WebSocket работают из внешней сети; certificate не истекает.
5. Participant session получает `403` на все admin routes.
6. Participant A не читает data B.
7. Blocked user получает `403`, а все его active sessions отозваны.
8. Stale revisions дают `409`, а не overwrite.
9. Logs не содержат email/session ID/session hash/password/steps.
10. Public leaderboard не содержит IDs, email или chain.
11. Rate limits проверены через общий NAT площадки.
12. Backup зашифрован и restore проверен.
13. Data notice и retention owner утверждены.
14. Admin block/adjustment/score создают audit events.
15. Streamlit light/dark error states остаются читаемыми и не раскрывают tracebacks.

## 18. Реакция на инцидент

```mermaid
flowchart TD
    detect["Detect security event"] --> contain["Contain access or service"]
    contain --> preserve["Preserve safe logs and request IDs"]
    preserve --> assess["Assess affected accounts and data"]
    assess --> rotate["Revoke sessions or rotate secrets"]
    rotate --> recover["Restore verified service"]
    recover --> notify["Follow organizer and legal notification process"]
    notify --> delete["Apply retention and remediation"]
```

При компрометации admin session блокируются admin-команды, отзывается конкретная или все admin sessions,
ротируются затронутые инфраструктурные secrets при необходимости и проверяется audit trail. Продолжение
мастер-класса не важнее защиты данных.
