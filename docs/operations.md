# Эксплуатация

Все команды выполняются из корня проекта с настроенной `.env`.
Для проверки используйте отдельный Compose-проект, собственные порты и тома.

## Текущая модель

`AML_PROBABILITY_MODEL_PATH` указывает на пакет `aml-game-organizer-settings-v1`.
В поставке остаётся только эта модель. `EXPANDED_ROUNDS_ENABLED=false` запрещает
создание новых игр. Для перехода с прежнего выпуска используйте новую базу или
штатный перезапуск игры; старые модели и раунды не поддерживаются.

Отсутствующий пакет, несовместимый контекст или изменённый pin приводят к ошибке.
Подробнее: [контракт модели](operations/model-support.md).

## Состояние и диагностика

```bash
docker compose ps
docker compose logs --tail=100 api ui
curl --fail http://127.0.0.1:8000/health/ready
```

API liveness не обращается к БД; readiness проверяет соединение и ревизию Alembic.
Пакет CatBoost проверяется при старте API, readiness также сообщает его identity.
UI liveness подтверждает только работу UI-процесса. Вход и игровые команды
дополнительно проверяют взаимодействие UI с API.
Ошибки API имеют `request_id`; не публикуйте секреты, сессии или полный `.env`.

`SESSION_TTL_MINUTES`, `LOGIN_MAX_FAILED_ATTEMPTS` и `LOGIN_LOCKOUT_MINUTES`
должны быть целыми числами больше нуля. Нулевые и отрицательные значения
отклоняются при старте; они не означают отключение защиты входа.

## Обновление

Используйте проверенный image digest и отдельную release-команду из
[deploy/README.md](../deploy/README.md). Перед обновлением дождитесь завершения
автосохранения, сделайте онлайн backup, сохраните предыдущий digest. Не собирайте
и не патчите образ на production. Миграции/seed выполняет только `release`.

## Онлайн backup и восстановление

Начальные цели: **RPO ≤24 часа, RTO ≤60 минут**. Это цели, а не измеренная
ёмкость production. `pg_dump -Fc` не требует остановки API/UI. Он сохраняет
согласованный снимок PostgreSQL: только дошедшие до API черновики. Несохранённый
ввод браузера и NiceGUI storage **исключены** из гарантии восстановления.
После восстановления все активные сессии отзываются; пользователи входят заново.

Запускайте утилиты клиентом PostgreSQL 16 или с `--container <postgres16>`.
Соединение задаётся PGHOST/PGPORT/PGUSER/PGDATABASE и защищённым PGPASSFILE либо
PGPASSWORD из credential store. Не помещайте пароль в URI/аргументы/логи.
Для container-режима передаются только имена переменных окружения.

```sh
python -m scripts.ops.backup_database --directory /private/aml-backups --image-reference "$AML_IMAGE" --offhost backup-host:/private/aml-backups --prune
python -m scripts.ops.restore_database /private/aml-backups/aml-TIMESTAMP.json --target-database aml_restore_drill
```

Backup создаёт уникальные UTC-имена, проверяет exit code, SHA-256 и размер,
публикует manifest только после завершения дампа. Off-host копия передаётся
через SSH; удалённый SHA-256 сверяется до копирования manifest. Каталог назначения
создаётся оператором заранее с правами 0700, SSH host key проверяется обычным
known_hosts. `--offhost` обязателен для принятой production-копии; локальный
успех не означает off-host защиту. Наличие SSH destination не проверено на
production в рамках локального теста.

Планировщик один: ежедневный запуск backup, отдельно мониторинг возраста
последнего **успешно скопированного и проверенного** manifest. При возрасте >24 ч
или ненулевом exit code — ошибка эксплуатации. Политика: последние 7 дневных
и 4 недельных копии (последняя копия каждого UTC-дня/ISO-недели).
`--prune` применяется только после успешного backup/copy и только к файлам
с валидным manifest/checksum в заданном каталоге. На backup-host запускайте ту
же версию утилиты с `--directory /private/aml-backups --prune-only`; сохраняйте
её exit code. Частичные и повреждённые копии нельзя считать пригодными.

Restore сначала сверяет checksum, создаёт **новую** БД `aml_restore_<name>`;
существующая БД не очищается и не заменяется. Восстановление выполняется одной
транзакцией с `--exit-on-error`, затем отзываются сессии. При ошибке целевая
БД остаётся для диагностики, не переключайте на неё приложение.
Запустите matching image из manifest в изолированном проекте с этой БД,
проверьте readiness, вход обеих ролей, текущую игру, server drafts, результаты,
пользователей и аудит. Только после проверки возможен отдельный управляемый
перевод production. Откат образа сам по себе не откатывает схему.

Локальный drill 2026-09-25: два онлайн-снимка (editing draft и scored result)
в PostgreSQL 16, проверены количества пользователей/игр/сценариев/результатов/
аудита, статус сценария, отзыв сессий, отказ перезаписи существующей БД.
Измерено восстановление около 0,96–0,98 с для маленькой тестовой БД;
возраст копии около 1,25 с. Это не оценка production RTO/RPO.

## Периметр и доверенные proxy

Read-only проверка 2026-09-25: балансировщик Timeweb `143215`, публичный IP
`80.90.184.166`, backend `94.241.141.158:8080`, TLS 443→HTTP 8080 и HTTP 80→HTTP
8080; PROXY protocol выключен. SYN-заголовки на backend подтвердили source
`80.90.184.166`. Публичный домен `https://amlplay.ru/health/live` отвечает 200.
**Прямой HTTP `94.241.141.158:8080` тоже ответил 200**: текущий production
периметр ещё не исправлен. Конфигурация сервера/балансировщика не изменялась.

В новой production compose публикуется только nginx ingress; UI/API/DB остаются
внутри сети. Allowlist проверяет исходный socket peer до real-IP преобразования,
поэтому поддельный X-Forwarded-For не открывает ingress. Разрешён проверенный LB
и loopback health check. Перед rollout повторно проверить все source IP probes
и WebSocket; при изменении LB адресов обновить allowlist. Loopback binding
подходит только локальному proxy и сломает существующий внешний балансировщик.

Nginx принимает X-Forwarded-For только от LB и передаёт UI один разрешённый адрес;
перед production rollout проверить, что LB добавляет настоящий socket IP справа
и не пропускает клиентскую подмену. Произвольным X-Forwarded-* доверять нельзя.
HTTP→HTTPS redirect должен быть обеспечен на внешней TLS-границе; существующее
правило HTTP 80 найдено, изменение его поведения в production не выполнялось.

UI добавляет nosniff, Referrer-Policy и запрет embedding; при Secure cookie
включается HSTS. CSP пока report-only и допускает необходимые NiceGUI inline/eval
скрипты; браузерная проверка не заменяется наличием заголовка. Неизвестные HTTP
адреса возвращают русскую 404 без path/traceback. Access-log ingress отключён,
чтобы не сохранять IP, query strings и возможные секреты.

## Игра и учётные записи

Регистрация и вход используют общий ранний UI limiter и независимый API limiter
с состоянием в PostgreSQL. Лимиты: 10 попыток/мин на пару IP+email, 300/мин
на IP с burst 120. Они рассчитаны на регистрацию и вход 60 участников за NAT;
HTTP 429 содержит Retry-After. Неверный пароль больше не блокирует аккаунт
глобально: другой IP остаётся доступен; блокировка организатором сохраняется.
Ключи лимитера — SHA-256, устаревшие записи очищаются ограниченными пачками.

Production compose использует частную сеть 172.30.23.0/24: ingress .2, API .3,
UI .4, DB .5. При конфликте подсетей согласованно изменить сеть, адреса и CIDR.
UI доверяет forwarded IP только от ingress .2; API принимает клиентский IP
только от UI .4 с HMAC, привязанным к email, операции и времени (30 секунд).
Задайте отдельный случайный AUTH_CONTEXT_SECRET для API/UI и синхронизируйте
часы. Uvicorn proxy headers отключены: исходный peer проверяется приложением.
Без секрета используется socket IP; публичные заголовки не дают доверия.
GET текущей игры и карточек требует сессию участника.

Повторная регистрация существующего email сохраняет HTTP 409 для совместимости.
По этому ответу можно узнать наличие аккаунта; полная неперечисляемость
регистрации не заявляется и требует отдельного изменения пользовательского потока.

Штатный перезапуск игры выполняется организатором в UI: удаляет игровые данные,
сохраняет пользователей и сессии, создаёт новый `draft`.
`python -m scripts.seed_database --migrate --reset-game` — отдельный разрушающий
сброс при остановленных API/UI; обычный запуск его не выполняет.
При ошибке скоринга приём остаётся закрыт; после исправления причины повторить
расчёт в UI. Блокировка участника отзывает сессии; разблокировка требует входа.

## Пул БД и процессы API

API запускается через `python -m scripts.run_api`; `API_WORKERS` принимает 1–4.
NiceGUI остаётся одним процессом. Миграции и seed выполняет отдельный release,
никогда каждый worker. Каждый процесс держит свою модель и собственный пул:
`DB_POOL_SIZE` (1–100, по умолчанию 5), `DB_POOL_OVERFLOW` (0–100, 10),
`DB_POOL_TIMEOUT` (0 < секунды ≤ 120, 5), `DB_POOL_RECYCLE` (1–86400, 1800).
`DB_POOL_DISABLED=true` предназначен для инструментов с разными event loops;
параметры QueuePool не передаются в NullPool.

До изменения числа процессов проверьте PostgreSQL `SHOW max_connections`.
Бюджет: workers × (pool_size + overflow) + scoring_worker_pool + ops_connections + reserve должен
быть строго меньше max_connections. При 100 соединениях и резервах 10+10:
с отдельным worker (пул 2, overflow 0) один API-процесс использует бюджет 37,
два — 52. Это бюджет соединений, а не
доказательство ёмкости: RAM модели умножается на workers. Базовая конфигурация
остаётся 1×(5+10), пока измерения не обоснуют изменение.

Исчерпание пула возвращает 503 `database_busy`, `Retry-After: 1` и request ID.
Повтор сохранения должен использовать тот же idempotency key и revision:
нельзя выдавать новый ключ для команды с неизвестным исходом. Регрессия на
реальном PostgreSQL удерживает единственное соединение, проверяет 3-секундный
timeout, затем повтор и replay одной команды без второй ревизии.
Rollback настройки — вернуть предыдущие значения и пересоздать только API
на прежнем digest; не запускать миграции/seed повторно ради изменения workers.

## Retention сессий и вкладок

`python -m scripts.ops.purge_sessions` выводит только агрегаты dry-run.
`--apply` удаляет сессии, истёкшие или отозванные не менее 7 дней назад.
Параметры: `--retention-days 7 --batch-size 500 --max-batches 20`; один запуск
удаляет не более 10000 записей, каждая пачка коммитится отдельно. Запускайте
одним scheduler после регулярного backup. Команда не удаляет пользователей,
активные сессии, сценарии или аудит; повторный запуск безопасен.

UI очищает старые чистые записи вкладок при открытии страницы и сохранении:
TTL 7 дней, целевой лимит 10 записей. Лимит мягкий: dirty/pending команды и
живые страницы, включая окно ожидания reconnect, защищены независимо от TTL.
Закрытые чистые вкладки восстанавливают подтверждённый черновик через API.
Записи без старой метки времени считаются устаревшими только если они чистые
и не принадлежат живому клиенту. Не удаляйте NiceGUI storage целиком для
очистки: он содержит локальные неподтверждённые команды и page guards.

## Переход паролей на Argon2id

Образ читает Argon2id и прежний `$bcrypt-sha256$v=2,...`. Новый формат:
64 MiB, 3 прохода, 1 lane, соль 16 байт; одновременно не более четырёх
операций хэширования на процесс (до 256 MiB поверх памяти приложения).
Параметры заданы явно, а не зависят от изменяемых defaults библиотеки;
[argon2-cffi описывает проверку параметров и rehash](https://argon2-cffi.readthedocs.io/en/25.1.0/api.html).
Проверки покрывают Unicode, 128 символов, неверный пароль и два конкурентных
входа: блокировка строки пользователя допускает только один rehash.

Production compose по умолчанию задаёт `PASSWORD_ARGON2_ENABLED=false`:
сначала выпустить этот dual-reader на **все** API-процессы и сохранить его
digest как допустимую точку отката. Затем отдельным изменением среды включить
`PASSWORD_ARGON2_ENABLED=true`. После включения регистрация пишет Argon2id,
а успешный разрешённый вход обновляет старый хэш в транзакции создания сессии.
Неверный пароль, блокировка аккаунта и неверная аудитория хэш не меняют.
Disposable тестовые стенды включают новый формат по умолчанию.

С первой записью Argon2id откат разрешён только на dual-reader digest.
Выключение флага прекращает новые rehash, но не преобразует существующие хэши
назад. Старый verifier сохраняется до подтверждённой инвентаризации остатков
и готового восстановления доступа; календарный срок не является основанием
для его удаления. Production в ходе этой работы не переключался.

### Durable scoring worker (T13)

Release migrations once, then start API/UI and `scoring-worker` from the same
immutable image. The worker owns calculation; API requests only close admission,
freeze revisions/config/model pin and enqueue. POST score returns 202 and a job ID;
GET `/api/v1/admin/scoring-jobs/{id}` returns bounded progress metadata. Transitional
`?wait=true` waits up to 30 seconds for that same job, returning the old 200 summary
when ready and 202 otherwise. It does not calculate in the API process.

Worker defaults: two independent scorer threads, each CatBoost thread_count=1;
one active job at a time; DB pool 2+0; 30-second renewable fenced lease. Snapshot
limits are 1,000 scenarios and 64 MiB (`SCORING_MAX_SCENARIOS`,
`SCORING_MAX_SNAPSHOT_BYTES`). CPU tasks receive plain data, never ORM sessions.
After a hard stop, restart the same image: the expired lease is claimed with a new
owner/attempt. Progress starts again at zero; results appear only with the final
transaction. A stale owner cannot publish. Failed jobs expose a safe error and
permit an explicit score retry. Restart cancels active jobs and erases their
scenario snapshots while retaining lifecycle metadata. Do not remove the worker
while keeping an API/UI release that queues jobs.

Disposable verification: `python -m scripts.check_durable_scoring --directory
.local-run/scoring-lab --output scoring-verification.json` (requires the lab helper's
private state). It inserts calculation fixtures in the disposable DB, queues via
HTTP, kills the real worker on the 300-scenario run and checks recovery and atomic
publication. This fixture is not a registration/submit throughput measurement.
