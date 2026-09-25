# Исправления по полному ревью AMLautosim — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Этот документ планирует работы; его создание не означает, что исправления уже внедрены.

**Goal:** восстановить воспроизводимый выпуск и исправить подтверждённые ошибки без потери данных, совместимости сохранённых раундов и устойчивости мастер-класса.

**Architecture:** небольшие независимо проверяемые изменения поверх `5fc9dcc`. Сначала контракт пакетов, CI и эксплуатационные гарантии; затем точечные исправления, наблюдаемость и оптимизация по замерам. Переписывание движка и перенос исследовательского контура — отдельная последующая работа.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, SQLAlchemy/asyncpg, PostgreSQL 16, NiceGUI, CatBoost, pytest, Ruff, Docker Compose, Git LFS.

**Spec:** [full-review-2026-09-25.md](../../verification/full-review-2026-09-25.md), с поправками и решениями ниже. Не все варианты из исходного отчёта принимаются к реализации.

**Дополнение пользователя:** отдельным этапом проработать лаконичный мобильный интерфейс и кросс-браузерность — T15. Это дополнительное требование, оно не входит в 40 ID исходного отчёта.

## 1. Итог проверки отчёта

**Согласен с основной картиной проблем, но не со всеми формулировками, приоритетами и рецептами.** P0 с окончаниями строк подтверждён независимым сравнением SHA-256 исходников из git. Исправления следует внедрять с учётом следующих уточнений.

### Что проверено в этой сессии

- Прочитан полный отчёт; ключевые выводы сопоставлены с кодом `5fc9dcc` в существующем worktree `AMLautosim-worktrees/aml-probability-v1`. Его рабочее дерево было чистым.
- Локальный основной каталог остаётся на `master@b441e04`; `origin/master` и `feature/aml-probability-v1` указывают на `5fc9dcc`. Это локальные refs, удалённый сервер git не опрашивался.
- Для всех девяти `compatibility_sources` текущего пакета сравнены хэши LF/CRLF с git-объектами `5fc9dcc`: восемь совпадают только с CRLF, `aml_context.py` — только с LF.
- На установленном FastAPI/Pydantic выполнен изолированный TestClient-эксперимент с предложенным `Literal[8, 10]` и альтернативой `IntEnum`.
- Проверены код старта, readiness, удаления аудита, модели FK, блокировки аккаунтов, скоринга, лимита покупок, опроса UI и существующего `GameEditor`.
- Полные pytest, API-тесты с PostgreSQL, нагрузка, dependency audit и live production в этой сессии **не запускались**. Числа 79 ошибок, 374 мс, 45 VU, размер LFS и число замечаний Ruff остаются данными исходного отчёта, а не новыми измерениями.

### Поправки, влияющие на реализацию

1. **REL-01: нельзя нормализовать все файлы через общий `file_hash`.** Он используется и для исходников, и для артефактов. Оставить побайтовые хэши `.cbm`, package JSON и датасетов; ввести отдельное, версионированное правило только для исходников. Иначе изменятся связанные хэши acceptance/manifest и идентичность исторических пакетов.
2. **REL-02: `git add --renormalize .` обновляет индекс, а не переписывает рабочие файлы в LF.** Для чистого воспроизведения нужен новый checkout с правилами EOL. Не применять массовую команду в рабочем дереве пользователя. См. [git-add](https://git-scm.com/docs/git-add#Documentation/git-add.txt---renormalize).
3. **REL-03: равенство production коммиту `5fc9dcc` не доказано.** Вступление отчёта сильнее его же описания патченных образов. До сверки image digest, revision и серверного compose считать `5fc9dcc` проверяемой кодовой базой, а происхождение работающего образа — открытым вопросом.
4. **DATA-01: теряется история блокировок, но не все сведения о текущей блокировке.** В `users` остаются `blocked_reason`, `blocked_at`, `blocked_by_user_id`. У `audit_events.round_id/scenario_id` нет `ON DELETE SET NULL`; сохранение событий без изменения ссылок сломает restart по FK. Нужны миграция и сохранённые идентификаторы удаляемых объектов в metadata.
5. **BUG-04: предложенный `Literal[8, 10] = Query(10)` не подходит без преобразования строк.** Эксперимент: default → 200, явные `8` и `10` → 422. `IntEnum` даёт 200 для обоих значений и 422 для `9`/`abc`; используем его. Сервисная проверка остаётся до advisory lock.
6. **ARCH-02: `GameEditor` уже существует** в `ui/nicegui/game.py`; `ParticipantScreen` использует его. Нужны выделение компонентов рендера и более чёткие границы, а не создание второго контроллера. Импорты общих модулей сами по себе не доказывают необходимость одного образа.
7. **PERF-01/02: 30-секундный таймаут не доказывает исчерпание пула.** HTTPX с большим лимитом также нельзя объявить исключённой причиной только по числу соединений. Однопроцессность — ограничение архитектуры, не самостоятельный P1-дефект. Диагноз требует времени ожидания пула, SQL, event loop, очереди HTTP и загрузки каждого процесса.
8. **PERF-04: `to_thread` не гарантирует ускорения CPU-кода Python.** Сначала убрать повторную работу; перенос в поток проверять замерами задержек и GIL. Передавать обычные данные, без ORM/AsyncSession. Ограничение описано в [документации asyncio](https://docs.python.org/3/library/asyncio-task.html#asyncio.to_thread).
9. **PERF-06: «300 участников» — оценка по времени, не подтверждённая ёмкость.** Потоки CatBoost проверяются экспериментом; `BackgroundTasks` без сохраняемого задания не обеспечивает восстановление после перезапуска.
10. **PERF-05: обновлять рейтинг один раз недостаточно**, если после расчёта меняется блокировка участника. Нужна инвалидация результатов; push всем клиентам не должен одновременно запускать десятки полных запросов.
11. **SEC-01: 10 входов/минуту на IP опасны для аудитории за общим NAT.** Нужны составные лимиты и проверка массового входа. Открытая регистрация уже раскрывает существование email через `email_already_registered`; одна правка lockout не устраняет все способы перечисления.
12. **SEC-02: `127.0.0.1:8080` допустим только с локальным proxy.** Внешний балансировщик не сможет обращаться к loopback сервера. Для него — private interface либо firewall с проверенным allowlist. CSP проверять с WebSocket и скриптами NiceGUI.
13. **DATA-03: восстановление без NiceGUI storage имеет цену.** В нём есть локальные, ещё не сохранённые на API изменения `workspace_play`; нельзя объявлять их заведомо ненужными. Отдельно задать гарантию сохранности серверных черновиков и предел потери локальных изменений. `pg_dump` допускает согласованный online backup БД: [PostgreSQL 16](https://www.postgresql.org/docs/16/app-pgdump.html).
14. **ARCH-01/06: отсутствие production pin не означает, что код/артефакт не нужен.** Учитывать тесты, воспроизведение обучения и архивные релизы. Удаление LFS-путей из HEAD не очищает историю. Историю git в этом плане не переписываем.
15. **PERF-07:** проверка `mtime/size` не равноценна проверке содержимого; отказ от проверки исходников не отменяет хэширования модели. Оптимизацию integrity не включать в срочный релиз без отдельного контракта неизменяемости пакетов.

### Решение по каждому пункту

«Принять» означает включить проблему в план; это не утверждение, что все числа исходного отчёта повторно измерены.

| ID | Решение | Работа |
|---|---|---|
| REL-01 | Принять P0; раздельные хэши исходников и артефактов | T01 |
| REL-02 | Принять; исправить рецепт восстановления checkout, учесть legacy verifier | T01 |
| REL-03 | Принять; production provenance ещё проверить | T00, T03 |
| REL-04 | Принять; readiness учитывает реально нужные модели | T03 |
| REL-05 | Принять как долг воспроизводимости ML; не скрывать новые runtime-регрессии | T02, T14 |
| REL-06 | Принять; CI до оптимизаций | T02 |
| PERF-01 | Принять наблюдавшийся отказ; причина пока гипотеза | T07, T11 |
| PERF-02 | Принять как вариант масштабирования после замера | T11 |
| PERF-03 | Принять; измерить разные виды правок, не только добавление | T10 |
| PERF-04 | Принять повторные преобразования; поток не считать готовым решением | T09 |
| PERF-05 | Принять; начать с лёгкого статуса и инвалидации рейтинга | T08 |
| PERF-06 | Принять ограничение синхронного запроса; численный потолок условный | T13 |
| PERF-07 | Отложить P3 до профиля; не ослаблять integrity попутно | T14 |
| DATA-01 | Принять P1 с поправкой про поля users и FK | T05 |
| DATA-02 | Принять прозрачность закрытия; сохранение abandoned — отдельное продуктовое расширение | T08 |
| DATA-03 | Принять; online backup + проверяемое восстановление | T06 |
| DATA-04 | Принять пагинацию; фильтр по last_login не считать точным членством в игре | T12 |
| DATA-05 | Принять; одна эксплуатационная задача, не scheduler в каждом API worker | T12 |
| DATA-06 | Принять ограничение storage; шифрование тем же ключом не решает компрометацию хоста | T12 |
| SEC-01 | Принять P1; NAT, доверенный IP и защита API входят в критерии | T06 |
| SEC-02 | Принять как историческое наблюдение; перепроверить периметр | T00, T06 |
| SEC-03 | Принять миграцию формата; собственную реализацию bcrypt-sha256 не выбирать | T12 |
| SEC-04 | Принять как пробел проверки, не как найденную уязвимость | T02 |
| SEC-05 | Принять явный контракт доступа, безопасные request IDs и логи; часть уже валидируется | T06, T07 |
| BUG-01 | Принять P1; единый effective limit для движка и snapshot | T04 |
| BUG-02 | Принять; сохранять безопасные доменные ошибки | T05 |
| BUG-03 | Принять; доступ к аккаунту не зависит от раунда | T05 |
| BUG-04 | Принять проблему; заменить неработающий рецепт на IntEnum | T04 |
| BUG-05 | Принять буквальный поиск, это не SQL injection | T12 |
| BUG-06 | Принять как небольшую правку текста | T12 |
| UX-01 | Принять; определить смысл каждого счётчика | T08 |
| UX-02 | Продуктовое поведение, не доказанный дефект; пока пояснение сброса | T10 |
| UX-03 | Принять; своя строка вне top-N | T08 |
| ARCH-01 | Принять инвентаризацию; удаление только с доказательством ненужности | T14 |
| ARCH-02 | Принять декомпозицию рендера, сохранить существующий GameEditor | T10 |
| ARCH-03 | Принять Settings и абсолютные пути; две модели не объединять одной переменной вслепую | T03, T11 |
| ARCH-04 | Принять постепенное усиление; не все 101 замечание являются дефектами | T14 |
| ARCH-05 | Принять; диагностика раньше настройки производительности | T07 |
| ARCH-06 | Принять организацию материалов; массовый перенос не нужен срочному релизу | T14 |
| ARCH-07 | Принять часть мелочей; локальные импорты и язык комментариев сами по себе не баги | T14 |

## 2. Global Constraints

- База реализации — `5fc9dcc` или проверенный более новый потомок; не переносить исправления вслепую на `b441e04`.
- Python 3.13 и PostgreSQL 16; платформы проверки — Linux и Windows.
- Не менять предсказания, признаки, округление и игровой контракт при исправлении только упаковки/EOL. Для функциональных исправлений отдельно указать ожидаемое изменение и проверить сохранённые раунды.
- Старые `risk_model` identities поддерживаются только после проверки совместимости. Добавление старого pin в allowlist само по себе не доказывает совместимость.
- Любая правка файла из `inference_sources`/`compatibility_sources` требует проверки и контролируемого перевыпуска пакета в том же изменении. Иначе следующий релиз снова отключит модель.
- Побайтовая integrity-проверка `.cbm` и артефактов сохраняется; не переписывать исторические research-хэши общей нормализацией.
- Не передавать `AsyncSession`, ORM-объекты или изменяемые UI-элементы между потоками.
- Ревизии, идемпотентность submit/score, запрет редактирования после cutoff и атомарность результатов сохраняются.
- Нагрузку и восстановление выполнять на отдельном стенде; реальные данные и секреты не помещать в git/логи. Удаление production-аккаунтов не является автоматической частью плана.
- Новые миграции добавлять после `0001_current_schema.py`; уже применённую миграцию не переписывать.
- Мобильный и настольный интерфейсы используют один GameEditor и одинаковые правила игры. Лаконичность достигается иерархией и раскрытием подробностей, без скрытия ошибок, статуса сохранения или необходимых действий.

## 3. Review Focus

1. LF/CRLF, побайтовая порча модели и старые pins: одинаковые исходники работают, повреждённый пакет отклоняется — T01.
2. Restart при событиях блокировки и ссылках на сценарии: история сохраняется, FK не мешают завершению — T05.
3. Одновременный save/submit/close/restart: нет потери подтверждённой записи и частично опубликованных результатов — T05, T08, T13.
4. Общий NAT, несколько вкладок, reconnect и смена раунда: легитимный участник входит, устаревший ответ не перезаписывает черновик — T06, T08, T10.
5. Старый bcrypt-sha256, отказ процесса во время расчёта/backup, откат образа: доступ и восстановление проверены на сохранённых данных — T06, T12, T13.

## 4. Порядок и критерии перехода

| Этап | Задачи | Условие завершения |
|---|---|---|
| A. Воспроизводимость | T00 → T01 → T02 → T03 | чистый checkout, обязательный CI, образ с известным SHA, readiness |
| B. Корректность и эксплуатация | T04, T05, T06 | корректные лимиты/версии, аудит переживает restart, проверены backup и вход |
| C. Ёмкость и интерфейс | T07 → T08 → T09 → T10 → T15 → T11 | компактный адаптивный UI, браузерная матрица, baseline/after и нагрузочный gate |
| D. Удобство и сопровождение | T12, T13, T14 | закрыты выбранные P2/P3; остаток долга имеет явный статус |

T07 можно выполнять сразу после A. Исправление подтверждённого внешнего доступа к 8080 и резервное копирование не должны ждать UI-рефакторинга. Срок «1–2 дня» из отчёта не принимается как обязательство: продолжительность зависит от CI, моделей, доступа к стенду и восстановления БД.

T15 имеет отдельный номер, чтобы сохранить ссылки на прежние задачи, но выполняется после T10 и до финального нагрузочного прогона T11. Аудит экранов и макеты T15 можно подготовить раньше; мобильную проработку не откладывать до завершения архитектурного долга T14.

В каждой задаче: воспроизводящий тест → зафиксированное падение по нужной причине → минимальная реализация → целевая проверка → отдельный commit. Для эксплуатационных задач вместо unit-теста — воспроизводимая проверка стенда. Ниже команды относятся к корню **ветки реализации**, где `python` указывает на её virtualenv.

## 5. Задачи реализации

### T00. Зафиксировать базу и проверяемый стенд

**Файлы:** создать `docs/verification/remediation-2026-09-25/baseline.md`; исходный отчёт оставить без переписывания.

- [ ] Сверить `git status --short`, `git rev-parse HEAD`, `git worktree list`; создать ветку от проверенной базы с сохранением чужих изменений.
- [ ] Записать Python/lockfiles, package identity, список реально используемых runtime-пакетов. Секреты из `.local-run` не включать.
- [ ] Получить read-only инвентаризацию deployment: image digest/revision, compose без раскрытия secrets, опубликованные порты, маршрутизацию балансировщика, используемые model pins. Если доступа нет, явно оставить production-сверку невыполненной; остальные локальные задачи продолжать.
- [ ] Отдельно собрать baseline unit/API/research и smoke на disposable PostgreSQL. Сохранить команды, exit codes и JUnit как артефакты проверки, не объявлять прежние результаты свежими.

**Приёмка:** кодовая база и production не смешаны в утверждениях; известен перечень моделей, которые нельзя удалить. Commit: `docs: record remediation baseline`.

### T01. Исправить EOL-контракт и загрузку пакетов

**Изменить:** `.gitattributes`, `services/game_classifier.py`, `scripts/package_game_classifier.py`; пути сервисов здесь и далее относительно `src/aml_workshop_simulator/`.
**Создать:** `services/source_hashing.py`, `scripts/release_runtime_compatibility.py`, `tests/unit/test_source_hashing.py`.
**Проверить/при необходимости изменить:** `services/aml_risk_model.py`; текущие release manifests и legacy manifest, `tests/unit/test_game_classifier_release.py`, `test_pinned_game_packages.py`, `test_runtime_package.py`.

**Интерфейс:** `source_sha256(path: Path) -> str`; raw `file_hash` остаётся прежним. Новое поле release `source_hash_mode="lf-v1"`; отсутствие поля означает прежний `raw-v1`. Не подбирать LF/CRLF эвристически для каждого файла.

- [ ] Добавить тест канонического хэша и отдельные тесты, что raw artifact hash реагирует на изменение байтов:

```python
def test_source_hash_is_independent_of_eol(tmp_path):
    from src.aml_workshop_simulator.services.source_hashing import source_sha256
    lf, crlf = tmp_path / "lf.py", tmp_path / "crlf.py"
    lf.write_bytes(b"value = 1\n")
    crlf.write_bytes(b"value = 1\r\n")
    assert source_sha256(lf) == source_sha256(crlf)
    crlf.write_bytes(b"value = 2\r\n")
    assert source_sha256(lf) != source_sha256(crlf)
```

- [ ] Реализовать нормализацию только в source hash:

```python
def source_sha256(path: Path) -> str:
    return sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
```

- [ ] Переключать verifier/packager по `source_hash_mode`. Для legacy v8 отдельно проверить его source checksum contract; не менять общий `file_sha` для бинарных артефактов.
- [ ] Перевыпустить текущий release после всех изменений его хэшируемых исходников; сохранить прежнюю полную identity до изменения. Добавить её в `compatible_identities` только после совпадения features, probabilities и SHAP на сохранённых примерах; убрать точные дубли identity.
- [ ] В скрипте перевыпуска принимать явный путь пакета; печатать список изменённых source hashes и старую/новую identity. Не перегенерировать dataset/acceptance без изменения их содержания. Проверить связи manifest → model, acceptance → manifest/readback/gameplay.
- [ ] Установить LF для перечисленных source-файлов, не переопределять `-text` для package JSON и LFS. Проверить новым checkout, не массовым переписыванием пользовательского дерева.
- [ ] Проверить LF- и Windows-checkout, изменённый байт `.cbm`, изменённую строку исходника, старый pin, неизвестный pin, v8 и v10. Сбой модели должен оставаться fail-closed.

**Команда:** `python -m pytest tests/unit/test_source_hashing.py tests/unit/test_game_classifier_release.py tests/unit/test_pinned_game_packages.py tests/unit/test_runtime_package.py -q`.
**Приёмка:** одинаковые исходники LF/CRLF загружаются; изменённый код/артефакт отклоняется; численные результаты не меняются. Commit: `fix: make runtime source hashes independent of checkout EOL`.

### T02. Ввести обязательный CI и видимый research baseline

**Изменить:** `pytest.ini`, `tests/conftest.py`, `tests/README.md`, маркировку тестов, dev dependency lock.
**Создать:** `.github/workflows/ci.yml`, `.github/workflows/dependency-audit.yml`, `tests/research-baseline.json`.

- [ ] Явно классифицировать тесты, а не переносить все упавшие в research. Runtime включает контракт, inference, модели, UI, API и конкурентность. Генерация/обучение/пересборка датасетов — research; `tests/load` — отдельный load job.
- [ ] Зарегистрировать `runtime`, `research`, `load`; проверять при collection отсутствие неклассифицированных тестов и случайного двойного назначения runtime/research. Не использовать широкий `--ignore` для всех `test_aml_*`.
- [ ] Linux/Windows: установка lockfile, LFS только необходимых пакетов, `ruff check src scripts tests migrations`, `pytest tests/unit -m runtime -q`.
- [ ] Linux с `postgres:16`: выполнить миграции и `pytest tests/api -q`; передать `TEST_ADMIN_DATABASE_URL`, который требует `tests/conftest.py`, и право создавать disposable БД. Отдельно smoke собранного Docker-образа с readiness и стартом UI.
- [ ] Research job запускать отдельно с явным списком известных failing node IDs/причин. Допустим неблокирующий исходный baseline; новые падения и исчезновение runtime-тестов должны быть видны. После восстановления воспроизводимости перевести job в обязательный.
- [ ] Подключить `pip-audit -r requirements.txt` и отдельную проверку ML-lockfile по расписанию/изменению зависимостей. Ошибку сети отличать от успешного аудита, исключения делать адресными и с датой пересмотра.
- [ ] Проверить workflow пробным PR; оформить required checks в настройках репозитория после появления jobs.

**Приёмка:** чистая машина ловит EOL-регрессию; runtime/API/image проверки обязательны, research-долг виден. Commit: `ci: gate runtime releases and report research regressions`.

### T03. Сделать выпуск и старт воспроизводимыми

**Изменить:** `deploy/Dockerfile`, `docker-compose.yml`, `api/main.py`, `api/routers/health.py`, `schemas/health.py`, `core/config.py`, `services/model_scoring.py`, `ui/nicegui/app.py`, `.env.example`, `deploy/README.md`.
**Создать:** `deploy/compose.production.yml`, `deploy/.env.production.example`, `.github/workflows/release.yml`, `core/ui_config.py`.
**Тесты:** `tests/unit/test_runtime_settings.py`, `tests/unit/test_runtime_package.py`, `tests/api/test_bootstrap.py`, `tests/api/test_contract.py`.

- [ ] Добавить сценарии: v10 стартует без legacy-пакета при отсутствии v8-раунда; реально нужный pinned package недоступен → readiness 503; liveness не обращается к БД/модели.
- [ ] Убрать безусловный `get_model_scorer()` из lifespan. Проверять текущий пакет; legacy загружать по запросу v8. Readiness учитывать доступность пакета текущего сохранённого раунда, а не только default v10.
- [ ] Пути default разрешать от корня проекта; абсолютные overrides сохранять. Настройки UI валидировать через `UISettings`, имена `AML_MODEL_PATH` и `AML_PROBABILITY_MODEL_PATH` документировать как разные назначения.
- [ ] В release job строить один образ из точного commit, фиксировать базовый image digest и lockfiles, добавлять OCI revision/source. Публиковать commit tag и digest; production ссылается на digest. Не патчить файлы наследованием образа.
- [ ] Production compose не монтирует произвольный host `config/` поверх проверенных файлов образа; конфигурация и модели поставляются согласованно. Серверные полезные probe/backup инструменты перенести в git после проверки и удаления секретов.
- [ ] Миграции/seed выполнять одной release-командой до старта воркеров. Передавать `git_sha`/image reference через build metadata; показать безопасную версию в health/админке.
- [ ] Проверить чистую установку и обновление копии БД; записать предыдущий image digest и процедуру отката с совместимостью схемы.

**Команда:** `python -m pytest tests/unit/test_runtime_settings.py tests/unit/test_runtime_package.py tests/api/test_bootstrap.py tests/api/test_contract.py -q`; затем compose smoke в CI.
**Приёмка:** пересборка имеет проверяемое происхождение; текущая игра не зависит от отсутствующей ненужной legacy-модели. Commit: `build: ship traceable images and validate required model packages`.

### T04. Исправить лимиты покупок и проверку версии

**Изменить:** `domain/simulation.py`, `api/routers/admin/rounds.py`, `services/admin_rounds.py`.
**Создать:** `schemas/game_version.py`.
**Тесты:** `tests/unit/test_organizer_settings.py`, `tests/unit/test_participant_limits.py`, `tests/api/test_contract_versions.py`.

- [ ] В существующем тесте custom purchase limits проверять не только `purchase_total_exceeded`, но и строку `purchase_count.limit`. Параметры 2, 3, 5; для 5 разрешённая четвёртая покупка не должна выглядеть превышением. Отдельно проверить границу `N=limit` и `N=limit+1`.
- [ ] Вместо `3` использовать effective CardSpec с применённым override, тот же, что проверяет движок. Проверить отсутствие покупки среди разрешённых карт и legacy policy, не ввести новый второй источник лимитов.
- [ ] Ввести тип и применить к query-параметрам supported version:

```python
from enum import IntEnum

class GameVersion(IntEnum):
    legacy = 8
    current = 10

# В HTTP-обработчиках:
# schema_version: GameVersion = Query(default=GameVersion.current)
# В сервис передаётся int(schema_version).
```

- [ ] Проверить допустимые `8`/`10`, default, недопустимые `7`/`9`/`11`/`abc`; 422 возникает до загрузки config и lock. Прямой вызов сервиса также проверяет версию до `pg_advisory_xact_lock`.
- [ ] Применить процедуру перевыпуска T01 для изменённого `simulation.py`; отдельно подтвердить, что изменение отображаемого лимита не меняет модельные признаки/вероятности.

**Команда:** `python -m pytest tests/unit/test_organizer_settings.py tests/unit/test_participant_limits.py tests/api/test_contract_versions.py -q`.
**Приёмка:** UI, snapshot и серверная валидация показывают один лимит; поддерживаемые query versions работают. Commit: `fix: align purchase limits and validate game versions before work`.

### T05. Сохранить аудит и доменные ошибки

**Изменить:** `db/models/audit_events.py`, `services/admin_rounds.py`, `services/participants.py`, `services/scoring_run.py`, `api/routers/admin/participants.py`, `schemas/admin.py`, вызов управления доступом в `ui/nicegui/organizer.py`.
**Создать:** `migrations/versions/0002_preserve_audit_references.py`.
**Тесты:** `tests/api/test_audit_regressions.py`, `tests/api/test_auth.py`, `tests/api/test_scoring.py`, `tests/api/test_concurrency.py`.

- [ ] Воспроизвести restart после block/unblock с reason, actor и scenario-linked аудитом; ожидается сохранённая история, пустые старые игровые данные и новая игра.
- [ ] Добавить `ON DELETE SET NULL` к audit FK round/scenario. До удаления игровых данных копировать прежние IDs в metadata событий; сохранять `target_type/target_id`, reason и actor. Убрать безусловное удаление аудита.
- [ ] Писать `round_restarted` в той же транзакции: `previous_round_id`, `new_round_id`, число удалённых сценариев/результатов, actor и request_id. При неуспешном restart всё откатывается.
- [ ] Реализовать `PUT /admin/participants/{id}/access` без раунда, сохранив роль, expected_access_revision, персональный lock и отзыв сессий. Старый маршрут делегирует общей операции и сохраняет прежнюю форму ответа для совместимости.
- [ ] Для `ApplicationError` сохранять безопасные `code/message/request_id`, восстанавливать `closed`, коммитить событие и возвращать исходную доменную ошибку. Неожиданные исключения → общий `scoring_failed`, traceback только в логе.
- [ ] Проверить rollback частично рассчитанных результатов, повтор score, блокировку без раунда, race access_revision и применение миграции к копии существующей схемы.

**Команда:** `python -m pytest tests/api/test_audit_regressions.py tests/api/test_auth.py tests/api/test_scoring.py tests/api/test_concurrency.py -q`.
**Приёмка:** аудит не исчезает и не блокирует restart; причина ошибки модели понятна организатору. Commit: `fix: preserve audit history and scoring error semantics`.

### T06. Защитить вход и обеспечить восстановление

Эту задачу выполнять тремя отдельными проверяемыми изменениями: backup, perimeter, authentication.

**Файлы:** создать `scripts/ops/backup_database.py`, `scripts/ops/restore_database.py`, `ui/nicegui/login_limiter.py`; изменить `docs/operations.md`, `deploy/compose.production.yml`, `deploy/nicegui.nginx.conf`, `ui/nicegui/app.py`, `ui/nicegui/auth.py`, `services/authentication.py`, `api/routers/auth.py` и конфигурацию доверенного UI→API взаимодействия.
**Тесты:** `tests/api/test_auth.py`, `tests/api/test_nicegui_auth.py`; создать `tests/unit/test_login_limiter.py`, `tests/unit/test_ui_security_headers.py`.

- [ ] Backup: `pg_dump -Fc` без остановки приложений; имя с UTC timestamp, проверка exit code, checksum, off-host copy, политика 7 дневных/4 недельных. Secrets передавать через защищённое окружение/credential store, не аргументами команд.
- [ ] Восстановить dump в отдельную БД через `pg_restore`, запустить matching image, проверить readiness, текущий раунд, server drafts, результаты, пользователей и аудит. Зафиксировать время восстановления и возраст последней успешной копии. Принять начальные цели RPO ≤24 ч, RTO ≤60 мин как цели плана, проверить достижимость.
- [ ] Документировать, что база сохраняет только дошедшие до API черновики. Перед плановым обновлением дать autosave завершиться. NiceGUI storage либо отдельно защищённо сохраняется, либо явно исключён из гарантии восстановления; токены после восстановления отзываются.
- [ ] Perimeter: определить фактические source IP балансировщика, затем ограничить 8080 с сохранением health probes/WebSocket. Loopback использовать только с локальным proxy. Проверить доступ через домен и недоступность прямого HTTP извне.
- [ ] Настроить Secure cookie для production, `nosniff`, Referrer-Policy, frame policy, HTTPS HSTS; CSP сначала проверить в report-only. Добавить русскую 404 без traceback, включая обычный HTTP и переходы из UI.
- [ ] Authentication: получать client IP только из проверенной proxy chain; передача этого контекста в API должна быть доверенной, внешние произвольные заголовки игнорируются. API сохраняет собственные ограничения, доступ к нему ограничен сетью.
- [ ] Начальные настраиваемые лимиты для стенда: пара `(IP, normalized_email)` — 10 попыток/мин; агрегат IP — burst 120, 300/мин. Это исходные параметры эксперимента, а не доказанные production defaults. Проверить 60 легитимных входов/регистраций за минуту с одного IP и последовательные атаки на аккаунты.
- [ ] Убрать возможность lockout аккаунта для всех IP чужими неуспешными попытками; сохранить отдельную административную блокировку. Дорогую dummy verification делать после раннего rate limit. Ошибки неверного входа для известного/неизвестного email имеют одинаковый внешний контракт.
- [ ] Явно зафиксировать политику duplicate-registration response: сохранение 409 означает остаточную возможность узнать зарегистрированный email. Если требуется полная неперечисляемость — это отдельное изменение регистрации/восстановления доступа, не объявлять его уже решённым.
- [ ] Закрепить решение о публичности current/cards: в текущей закрытой игре требовать участника; проверить bootstrap/UI до ужесточения. Не помещать raw session/password/email в метрики и логи.

**Проверка:** unit/API auth tests, успешное восстановление и внешняя проверка стенда. Приёмка не сводится к наличию cron или middleware. Commits: `ops: verify online backup and restore`, `security: restrict ingress and harden UI responses`, `security: rate limit authentication without locking out workshop NAT`.

### T07. Добавить измерения до оптимизации

**Изменить:** `api/main.py`, `api/routers/health.py`, `db/session.py`, `ui/nicegui/client.py`, `ui/nicegui/app.py`.
**Создать:** `core/observability.py`, `tests/load/nicegui_driver/runner.py`, `tests/load/nicegui_driver/README.md`, `tests/unit/test_observability.py`.

- [ ] Собирать route-template/status/duration, SQL duration, ожидание получения соединения, checked-out/overflow, event-loop lag API/UI, CPU/RSS процессов, HTTP UI→API in-flight/latency, число UI clients.
- [ ] Выдавать метрики через внутренний служебный endpoint; никакой публичной выдачи SQL, конфигурации или пользовательских данных. JSON-логи: server request_id, duration, route, status; client correlation ID хранить отдельно и валидировать. Входящий request ID сейчас уже ограничен ASCII/длиной — сохранить эти ограничения.
- [ ] Логировать исключения readiness с request_id; не смешивать liveness с доступностью БД. Проверить отсутствие токенов/паролей в логах на тестовых ошибках.
- [ ] Сохранить воспроизводимый WebSocket-драйвер и его версии. Существующий `tests/load/test_nicegui_workshop.py` работает с API/controller и не заменяет browser/WebSocket/proxy benchmark.
- [ ] Снять baseline 20/30/45/60 VU на стенде с заранее созданными аккаунтами; регистрацию замерить отдельно. Сохранить dropped/time-out actions, а не только latency успешных ответов; контролировать CPU и сеть генератора.

**Приёмка:** для деградации есть временная связь между действием UI, API, SQL/pool и lag; причина либо подтверждена, либо явно остаётся неизвестной. Commit: `perf: instrument workshop traffic and preserve load harness`.

### T08. Сократить polling и сделать закрытие игры прозрачным

**Изменить:** `services/participant_state.py`, `services/results.py`, `services/scoring_run.py`, `schemas/rounds.py`, `schemas/admin.py`, `schemas/leaderboard.py`, `api/routers/rounds.py`, `ui/nicegui/game.py`, `ui/nicegui/participant.py`, `ui/nicegui/organizer.py`.
**Создать:** `schemas/round_status.py`, `tests/api/test_round_status.py`.
**Тесты:** `tests/unit/test_game_poll_races.py`, `tests/api/test_scoring.py`, `tests/api/test_nicegui_game.py`.

**Интерфейс:** authenticated `GET /rounds/current/status` возвращает `round_id`, `status`, `config_version`, персональную `scenario_revision`, `access_revision` и `results_version`. `results_version` меняется при публикации результатов и изменении доступа, влияющем на рейтинг; начальная реализация может вычислять его из данных без отдельного scheduler.

- [ ] Проверить неизменённый статус без `game_config`, переходы active/closed/scoring/completed, отсутствие раунда, block/unblock и сценарий второй вкладки.
- [ ] Полное состояние получать при изменении версии; bounded cache по `(round_id, config_version)` без изменения объекта конфигурации. Клиентские sequence/generation guards сохранить.
- [ ] Рейтинг обновлять по `results_version`, reconnect и кнопке. Не использовать `generated_at` как признак изменения — он меняется на каждом ответе. При одинаковом содержимом не делать `board.clear()`.
- [ ] Добавить `current_user_row` для участника вне top-N, не раскрывая закрытые/admin-поля. Тест: 201 участник, лимит 200; tie-break/rank соответствует общему рейтингу.
- [ ] В админке показать `editing`, `submitted`, `scored` по текущему round_id. `registered_total` обозначить как общее число аккаунтов, не выдавать его за число участников текущей игры; отдельного точного membership в модели пока нет.
- [ ] Перед закрытием показывать число editing/submitted. В транзакции cutoff записать фактический `deleted_drafts_count` в `round_closed`; число в подтверждении — предварительное и может измениться из-за конкурентного submit.
- [ ] Участнику явно сообщить, что неотправленный черновик удаляется при закрытии, и показать изменение статуса. Дедлайн/abandoned не вводить без отдельного продуктового решения.
- [ ] Проверить race submit/close и сохранение финальных счётчиков. Отдельно замерить падение bytes/query rate, не объявлять cache решением всех проблем БД.

**Команда:** `python -m pytest tests/api/test_round_status.py tests/unit/test_game_poll_races.py tests/api/test_scoring.py tests/api/test_nicegui_game.py -q`.
**Приёмка:** холостой опрос не передаёт config/рейтинг; изменения доступа видны; черновики посчитаны в cutoff audit. Commit: `perf: poll lightweight versions and expose admission counts`.

### T09. Убрать повторную канонизацию без изменения семантики

**Изменить:** `services/scenario_service.py`, `services/expanded_simulation.py`, `services/counterparties.py`, `services/aml_context.py`, `services/semantic_contract.py`, `services/scenarios.py`.
**Создать:** `tests/unit/test_scenario_preparation.py`.
**Тесты:** существующие `test_aml_context.py`, `test_semantic_v9.py`, `test_counterparties.py`, `tests/api/test_scenarios.py`.

- [ ] Зафиксировать before outputs для v8/v10: canonical steps, snapshot, blockers, payload hash, timeline; валидные и невалидные поля, повторяющиеся step_id, пустая/16-шаговая цепочка, разные настройки организатора.
- [ ] Добавить внутренний путь `build_snapshot_from_canonical(steps, specs, config, policy) -> dict`; публичные evaluate-входы продолжают валидировать произвольный ввод. Только `prepare_scenario` передаёт канонический результат во внутренний путь.
- [ ] Не использовать внешний флаг `already_validated`, доступный API-клиенту. Кэшировать только проверенную неизменяемую конфигурацию по содержательному config_version, с ограничением размера; не кэшировать изменяемый ORM Round.
- [ ] Сравнить snapshots/blockers/хэши до и после; тестировать, что prepare выполняет канонизацию один раз, но главное условие — одинаковое поведение.
- [ ] Повторить профиль 1/9/16 шагов. `to_thread` добавлять только при измеримом улучшении event-loop latency с bounded concurrency; рефакторинг не должен удерживать соединение БД дольше прежнего.
- [ ] Перевыпустить compatibility manifest через T01 и выполнить replay старых pins. Объединение preview/save оставить отдельным изменением API, если после этого оно ещё нужно.

**Команда:** `python -m pytest tests/unit/test_scenario_preparation.py tests/unit/test_aml_context.py tests/unit/test_semantic_v9.py tests/unit/test_counterparties.py tests/api/test_scenarios.py -q`.
**Приёмка:** прежняя семантика и меньше CPU/копирований, подтверждённые профилем. Commit: `perf: reuse canonical scenario preparation`.

### T10. Разделить компоненты UI и обновлять затронутые карточки

**Изменить:** `ui/nicegui/participant.py`, существующий `ui/nicegui/game.py`.
**Создать:** `ui/nicegui/components/step_card.py`, `ui/nicegui/components/resource_summary.py`.
**Тесты:** `tests/api/test_nicegui_participant_editing.py`, `tests/unit/test_correction_navigation.py`, `test_operation_amount_heading.py`, `test_game_poll_races.py`, `test_timeline_ui.py`.

**Интерфейс:** `StepCard.update(step: dict, *, index: int) -> None`; реестр элементов keyed by `step_id`. GameEditor продолжает владеть состоянием/API, виджеты не создают независимые autosave loops.

- [ ] Зафиксировать DOM/element identity неизменённой карточки при изменении соседней; отдельно add/delete/copy/reorder, суммы и ошибки.
- [ ] Выделить рендер карточки/сводки, сохранить обработчики и client ownership; обновлять существующие элементы, удалять listeners/timers вместе с карточкой. Перестановка обновляет также зависимые временные подписи и ошибки.
- [ ] Проверить caret/focus, scroll, открытые панели, navigation к ошибке, автосохранение и смену страницы при задержанном ответе API.
- [ ] Для UX-02 пока добавить понятное сообщение о сбросе ожидания при переносе в начало. Восстановление старого ожидания при возврате — отдельное изменение draft semantics, не скрытая часть refactor.
- [ ] Измерить полный объём сообщений на действие для 1/8/16 шагов. Цель ≤25 КБ для обычного изменения одной карточки при 8 шагах; добавление/перестановку измерять отдельно. Полная первичная загрузка не ограничивается этой цифрой.

**Команда:** `python -m pytest tests/api/test_nicegui_participant_editing.py tests/unit/test_correction_navigation.py tests/unit/test_operation_amount_heading.py tests/unit/test_game_poll_races.py tests/unit/test_timeline_ui.py -q`.
**Приёмка:** обновление поля не пересоздаёт цепочку и не теряет ввод; WebSocket payload уменьшился. Commit: `refactor: update participant cards without rebuilding the chain`.

### T11. Настроить пул и воркеры по измерениям

**Изменить:** `core/config.py`, `db/session.py`, `.env.example`, production compose и `docs/operations.md`.
**Тесты:** `tests/unit/test_runtime_settings.py`, `tests/api/test_concurrency.py`, load harness T07.

- [ ] Ввести `DB_POOL_SIZE`, `DB_POOL_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE`, `API_WORKERS`; валидировать диапазоны. При `DB_POOL_DISABLED=true` не передавать несовместимые параметры в NullPool.
- [ ] Сравнить конфигурации 1 и 2 API workers; 4 — только если есть улучшение. Миграция/seed выполняется один раз, как предусмотрено T03; NiceGUI пока один процесс.
- [ ] Бюджет: `workers * (pool_size + overflow) + ops_connections + reserve < max_connections`. Например, 2×(10+5)+10+10=50; это пример бюджета, а не обязательная production настройка. Учесть RAM загруженных моделей на каждый процесс.
- [ ] Короткий pool timeout 3–5 секунд испытывать с контролируемой перегрузкой; вернуть 503 с безопасным retry, не случайный 500. Не уменьшать таймаут без обработки ошибки и проверки идемпотентности повторного сохранения.
- [ ] Повторить по три прогона 45 и 60 VU после прогрева, отдельно массовый вход и score. Записать hardware/image digest, полный набор метрик T07 и все неуспешные действия.
- [ ] Выполнить двухчасовой soak через тот же тип proxy/WebSocket; проверить reconnect, число clients, RSS и очередь запросов.

**Предлагаемый gate мастер-класса:** 60 активных участников, 0 необъяснённых 5xx/потерянных действий, p95 edit ≤1,5 с, p95 канарейки ≤1 с, нет pool timeout; одноразовые выбросы и reconnect описаны. Это цели приёмки, не обещание текущей ёмкости. При непройденном gate публиковать только измеренную меньшую ёмкость.
**Приёмка:** выбрана самая простая конфигурация, проходящая gate; изменение имеет rollback. Commit: `perf: tune bounded API concurrency from load measurements`.

### T12. Исправить управление аккаунтами и накопление состояния

Выполнить отдельными commits; не объединять миграцию паролей с удалением данных.

**Изменить:** `services/participants.py`, `schemas/admin.py`, admin participants router, `ui/nicegui/organizer.py`, `ui/nicegui/app.py`, `ui/nicegui/participant.py`, `core/security.py`, `services/authentication.py`, `domain/simulation.py`, dependency input/lockfiles.
**Создать:** `scripts/ops/purge_sessions.py`, `ui/nicegui/storage_retention.py`, `tests/unit/test_storage_retention.py`, `tests/unit/test_password_migration.py`, `domain/russian_plural.py`.

- [ ] Пагинация: стабильный cursor по `id`, все аккаунты доступны; фильтр «со сценарием текущего раунда» называть именно так. Не выдавать recent login за точное участие. Тест: 501+ аккаунт, обход страниц без потерь/дублей, параллельная регистрация.
- [ ] Поиск: экранировать `\`, `%`, `_` при `ilike(..., escape="\\")`; проверить буквальные `%`, `_` и кириллицу.
- [ ] Очистка sessions: отдельная ops-команда с dry-run, периодом хранения 7 дней для expired/revoked, ограниченными batches. Выполнять одним scheduler; активная сессия не удаляется. Проверить FK и повторный запуск.
- [ ] Storage: TTL/лимит записей вкладок; не выкидывать dirty workspace только по LRU. В первую очередь удалять старые чистые/закрытые записи. Не терять активно открытые страницы/guard tokens. Тест: >10 вкладок, dirty/clean, reload и reconnect.
- [ ] Миграция паролей: новые записи Argon2id, старые `$bcrypt-sha256$v=2,...` проверяются прежним verifier и перехэшируются при успешном login. Использовать синтетические legacy hashes в тестах, не выгрузку production. Проверить Unicode, длинные пароли, неверный пароль и конкурентный login.
- [ ] Релиз миграции паролей должен читать оба формата до начала перехэширования. С этого момента откат разрешён только на образ с поддержкой обоих форматов. Не удалять legacy verifier по календарю без проверки остатка хэшей и механизма восстановления доступа.
- [ ] Добавить plural helper с тестами 1/2/5/11/21/22/25; поправить тексты без изменения rules. При изменении хэшируемого source применить T01.
- [ ] Подготовить dry-run инвентаризацию loadtest-аккаунтов. Удаление на production выполнять отдельно по конкретному списку после backup и проверки связанных данных; совпадение email prefix само по себе недостаточно.

**Проверка:** `python -m pytest tests/unit/test_storage_retention.py tests/unit/test_password_migration.py tests/api/test_auth.py tests/api/test_audit_regressions.py -q`; добавить API-тесты пагинации/поиска в новый `tests/api/test_participant_pagination.py` и прогнать его.
**Приёмка:** аккаунты доступны после 500-й записи, действующие сессии/черновики сохраняются, оба формата паролей работают. Commits по четырём группам: participants/search, retention, password migration, copy.

### T13. Устранить зависимость расчёта от времени HTTP-запроса

**Сначала эксперимент:** `services/scoring_service.py`, отдельный benchmark; сравнить 1/2/4 потока с `thread_count=1` и одинаковыми результатами. Общий scorer не считать потокобезопасным без проверки. Не передавать db session в executor. Ограничить RAM/очередь, не создавать unbounded gather.

**Целевое решение при необходимости долгого расчёта:** сохраняемое задание в PostgreSQL и отдельный worker, без обязательного Redis/Celery.
**Создать:** `db/models/scoring_jobs.py`, следующую свободную миграцию после T05, `services/scoring_jobs.py`, `scripts/ops/scoring_worker.py`, `tests/api/test_scoring_jobs.py`.
**Изменить:** `services/scoring_run.py`, `services/scoring_service.py`, admin rounds router, `schemas/admin.py`, `ui/nicegui/organizer.py`, production compose.

- [ ] Контракт: `POST /admin/rounds/{id}/score` → 202 `{job_id, state, done, total}`; повтор запроса возвращает то же активное задание. `GET /admin/scoring-jobs/{id}` выдаёт состояние/прогресс. Завершённый результат остаётся доступен через прежние results endpoints.
- [ ] Cutoff коммитится до постановки расчёта по сохранённой транзакционной схеме; постановку job сделать атомарной с переходом в scoring. Уникальность активной job по раунду, lease/attempt для восстановления после crash.
- [ ] Worker считает из зафиксированных config/pin/scenario revisions, пишет прогресс отдельно от публикации. Финальная запись результатов атомарна и проверяет, что раунд всё ещё соответствует заданию. Удалённый restart-ом раунд не воскрешается.
- [ ] Проверить crash до claim, после claim, на середине, перед публикацией; retry не создаёт дубликаты и не публикует частичный рейтинг. Две команды score и restart во время вычисления дают определённый результат.
- [ ] UI показывает done/total и безопасную ошибку, timeout HTTP больше не определяет максимальное число участников. Версию API/UI выпускать согласованно; промежуточный релиз должен понимать прежний sync response и новый 202.

**Команда:** `python -m pytest tests/api/test_scoring_jobs.py tests/api/test_scoring.py tests/api/test_concurrency.py -q`; затем полный score 60/300 сохранённых сценариев на стенде.
**Приёмка:** расчёт восстанавливается после остановки worker, результаты атомарны. Без crash/retry тестов фоновой задачу готовой не считать. Commit: `feat: run durable scoring jobs with recoverable progress`.

### T14. Закрывать архитектурный и исследовательский долг отдельно

**Файлы:** `ruff.toml`, создать `mypy.ini`, `resources/catboost_models/registry.json`, `docs/operations/model-support.md`; изменить classifier resolver, `deploy/Dockerfile`, metadata версии, docs/scripts по результату инвентаризации.

- [ ] Реестр пакетов строить из T00: package path, identity, current/legacy/research, runtime consumers. Тест resolver: current, каждый поддерживаемый старый pin, неизвестный pin и повреждённый пакет. Не строить путь из клиентского pin.
- [ ] `CURRENT.json` не объявлять ошибкой только потому, что он указывает на v8: сначала найти его потребителей. Развести указатели legacy/research/current runtime либо заменить документированным registry с миграцией потребителей.
- [ ] Убрать неработающий unlimited-пакет из runtime image только после replay всех его совместимых pins через текущий пакет. Не удалять research код на основании отсутствия вызова из runtime dispatcher.
- [ ] Для REL-05 выбрать проверяемый путь: закрепить последний реально воспроизводимый commit вместе с lockfiles, dataset/model hashes и seeds; изолированно повторить один dataset build и обучение/оценку. Не создавать выдуманный «рабочий тег 17.09» без прогона. Если такого commit нет, обновить генераторы под текущий контракт отдельным ML-планом с новой версией датасета; текущую модель автоматически не заменять.
- [ ] Включать Ruff `B`, `ASYNC`, `UP` постепенно. B008 исключать только для действительно штатных dependency/default patterns; B905 исправлять `strict=True` там, где равенство длин — инвариант, а не просто массовой заменой. B023 подтверждать поведением замыканий.
- [ ] Ввести type-check сначала для чистых контрактов/выбранных функций скоринга; строгость расширять после типизации границ numpy/pandas/CatBoost. Зелёный mypy с широким `ignore_errors` не считать результатом.
- [ ] Версию сервиса вынести в одну константу; описать commit/rollback контракт `get_db`; кешировать migration heads при неизменяемом каталоге образа. Локальные импорты переносить только после проверки отсутствия циклов и lazy-loading требований.
- [ ] Логи/JUnit/notebooks отделить от итоговых отчётов; перенос скриптов сопровождать исправлением импортов/CLI. Архивные LFS-артефакты переносить с manifest, checksums и проверкой восстановления ссылок. Не переписывать git history и не удалять архивы в рамках cleanup.
- [ ] PERF-07 оставить как baseline P3 либо отдельный проверяемый контракт: проверка при загрузке неизменяемого versioned пакета; изменение каталога означает новый instance/package path. `mtime/size` не использовать как доказательство целостности.

**Приёмка:** каждый cleanup имеет список потребителей и проходящие целевые тесты; research reproduction подтверждается запуском, а не сменой маркера. Делить на commits registry, research baseline/recovery, static checks и repository organization.

### T15. Проработать лаконичный мобильный интерфейс и кросс-браузерность

**Основание:** дополнительное требование пользователя. **Зависимости:** T08 задаёт статусы и счётчики, T10 — обновляемые компоненты карточек. **Результат:** единый адаптивный UI для участника и организатора; приоритет проработки — полный игровой путь участника на телефоне.

**Изменить:** `ui/nicegui/theme.py`, `ui/nicegui/app.py`, `ui/nicegui/participant.py`, `ui/nicegui/organizer.py`, `ui/nicegui/configuration.py`, `ui/nicegui/shap_result.py`, компоненты из T10; при необходимости компоненты контекста/истории, вызывающие переполнение.
**Создать:** `docs/verification/mobile-ui-2026-09-25/design.md`, `docs/verification/mobile-ui-2026-09-25/browser-matrix.md`, `tests/browser/test_mobile_workshop.py`, `tests/browser/test_responsive_layout.py`, `tests/browser/README.md`.
**Сохранить:** существующие API/UI-тесты редактирования, навигации к ошибкам, сумм и гонок автосохранения. Браузерные тесты запускаются на disposable стенде, не на production.

#### 1. Аудит и компоновка

- [ ] Пройти вход/регистрацию, условия игры, создание и правку цепочки, отправку, ожидание и результаты на узком экране. Зафиксировать лишние повторения, длинные объяснения, горизонтальную прокрутку и действия, которые трудно найти или нажать. Сохранить исходные screenshots для сравнения.
- [ ] Подготовить макеты основных состояний на 360 и 390 CSS px: пустая цепочка, редактирование, ошибка, сохранение/нет сети, отправленная цепочка и результат. Добавить настольный вариант для проверки общей иерархии; записать выбранную компоновку и причины в `design.md`.
- [ ] Основная компоновка: одна колонка; компактная сводка цели и ресурсов; одна раскрытая карточка редактирования, остальные — краткие резюме «операция / сумма / время». Подробные условия, история и объяснение модели раскрываются по запросу. Ошибка в свёрнутой карточке остаётся заметной и раскрывает нужное поле по нажатию.
- [ ] Визуально выделить одно главное действие текущего состояния: «Добавить операцию» для пустой цепочки, «Отправить» для готовой. Копирование/удаление и другие вторичные команды доступны через подписанное меню карточки; не полагаться на непонятные иконки или hover. Перестановка доступна кнопками, даже если дополнительно есть drag-and-drop.
- [ ] Статус «Сохраняется / Сохранено / Не удалось сохранить» и причина недоступности отправки видны без открытия справки. Не дублировать одинаковые предупреждения одновременно в нескольких блоках; подробности показывать по ссылке рядом с краткой причиной.
- [ ] Для организатора сохранить доступность настроек, счётчиков, закрытия/расчёта и списка участников. На узких экранах заменить широкие таблицы компактными строками/карточками; опасные действия оставить с понятным подтверждением. Не создавать отдельный набор бизнес-правил для мобильной версии.

#### 2. Адаптивность и взаимодействие

- [ ] Задать общие отступы, размеры текста и ширину контента в `theme.py`; адаптацию выполнять через layout/media queries, без определения интерфейса по User-Agent. Ввести только необходимые breakpoints по фактическому переполнению содержимого.
- [ ] На ширинах 320, 360, 390, 430, 768 и 1280 CSS px проверить все основные состояния. У страницы нет горизонтальной прокрутки; длинные названия/email/суммы не выталкивают действия за экран. Для действительно двумерных данных допустим отдельный явно обозначенный scroll-контейнер.
- [ ] Заложить области нажатия основных кнопок не менее 44×44 CSS px как проектное требование. Формы имеют постоянные подписи, понятные ошибки и подходящий `inputmode`; проверить денежный ввод с запятой/точкой, вставкой и экранной клавиатурой без изменения денежного контракта API.
- [ ] Проверить портретную и альбомную ориентацию, safe-area, изменение высоты браузерной панели и открытие клавиатуры. Закреплённая панель действий, если используется, не закрывает поле, ошибку или последнюю карточку; контент имеет необходимый нижний отступ. Диалоги помещаются в доступную высоту и прокручиваются.
- [ ] Не отключать пользовательский zoom. Проверить увеличение масштаба/текста до 200%, видимый keyboard focus, порядок Tab, доступные имена кнопок и раскрываемых секций. Состояния различимы не только по цвету; ошибки озвучиваются и позволяют перейти к полю. Выполнить короткий проход VoiceOver/TalkBack на доступных устройствах.
- [ ] При сворачивании браузера, возврате, reload и WebSocket reconnect сохранить корректный статус черновика; не показывать «Сохранено» для изменений, которые API ещё не подтвердил. Проверить отсутствие двойной отправки после повторного нажатия.

#### 3. Матрица браузеров и регрессии

**Политика поддержки:** на дату реализации зафиксировать точные версии ОС/браузеров; целевые семейства — Safari на iOS, Chrome на Android, Chrome/Edge/Firefox на desktop и Safari на macOS. Для основных мобильных платформ проверить текущую и предыдущую основную версию ОС/браузера, где доступно; недоступные комбинации отмечать как непроверенные. Не заявлять поддержку «всех браузеров» без границ.

| Среда | Проверка | Ключевые сценарии |
|---|---|---|
| iPhone / Safari | реальное устройство или сервис реальных устройств | клавиатура, safe-area, формы, отправка, фон/возврат, reconnect |
| Android / Chrome | реальное устройство или сервис реальных устройств | числовой ввод, touch, сворачивание карточек, диалоги, длинная цепочка |
| Windows / Chrome, Edge, Firefox | браузерный прогон | полный игровой путь, клавиатура, масштаб, организатор |
| macOS / Safari | браузерный прогон | формы, layout, результаты, reconnect |
| Chromium, Firefox, WebKit automation | воспроизводимые E2E в CI | размеры экранов, переходы, ошибки, сохранение и отправка |

- [ ] Настроить Playwright browser suite отдельно от NiceGUI user simulation. Зафиксировать версии runner/browser builds в тестовом окружении; использовать доступные роли/подписи и стабильные test IDs, а не внутренние динамические listener IDs.
- [ ] Автоматизировать полный путь: войти → добавить/изменить/переставить операции → увидеть и исправить ошибку → дождаться подтверждённого autosave → отправить → получить результат. Отдельно проверить поведение организатора на узком экране и горизонтальное переполнение при длинных данных.
- [ ] Для каждого движка прогнать проверки layout и сценариев на mobile viewport и desktop. Screenshot comparison использовать как дополнение к проверкам поведения; baseline разделять по browser/viewport. WebKit automation не считать подтверждением работы Safari на реальном iPhone.
- [ ] В `browser-matrix.md` записать дату, ОС, browser version, устройство/эмуляцию, image digest, результат сценариев и ссылки на артефакты. Не считать строку пройденной, если проверена только ширина окна другого браузера.
- [ ] После адаптации повторить измерения payload T10 и затем нагрузочный gate T11: свёрнутые карточки не должны незаметно создавать дополнительные polling loops или повторные API-запросы.

**Команды после настройки suite:** `python -m pytest tests/browser -q --browser chromium --browser firefox --browser webkit`; существующие `tests/api/test_nicegui_participant_editing.py`, `tests/unit/test_correction_navigation.py`, `tests/unit/test_game_poll_races.py` также должны пройти. Зависимости и запуск тестового сервера описать в `tests/browser/README.md`.

**Приёмка:** на 360/390 CSS px участник проходит полный игровой путь без горизонтальной прокрутки страницы, hover и уменьшения масштаба; основное действие, статус сохранения и блокирующая ошибка доступны сразу в соответствующем блоке. Детали доступны по раскрытию, обязательные поля и функции сохранены. На 320 CSS px интерфейс остаётся работоспособным. Пройдены автоматизированная матрица трёх движков и реальные iOS Safari/Android Chrome проверки; по непроверенным средам есть явный статус. Desktop layout и производительность не регрессировали.

**Commits:** `design: specify concise mobile workshop layouts`, `feat: adapt workshop UI for touch and small screens`, `test: cover mobile and cross-browser workshop flows`.

## 6. Выпуск и контроль результата

- [ ] Все 40 ID исходного отчёта имеют решение в таблице; закрывать ID только после его критериев, а не после merge соседнего улучшения.
- [ ] На release candidate пройти обязательные runtime/API/migrations/image checks T02; сохранить model identities, image digest и итоговый baseline/after.
- [ ] Проверить UI: регистрация/вход, редактирование/автосохранение, две вкладки, submit, close/score, повтор score, block/unblock, restart и рейтинг. Отдельно Firefox/Safari/мобильный viewport, 125% zoom, клавиатура и длительный reconnect.
- [ ] Пройти отдельный мобильный этап T15: компактная компоновка, touch/клавиатура, zoom до 200%, browser matrix и реальные iOS/Android проверки. Зафиксировать непроверенные среды и не выдавать эмуляцию за проверку устройства.
- [ ] Восстановить свежую резервную копию на отдельном стенде. Откат образа совместим с миграциями и обоими password formats; иначе указать конкретный forward-fix/restore порядок.
- [ ] Перед мастер-классом пройти нагрузочный gate T11 на релизном image digest. До этого не заявлять поддержку 60/300 участников.
- [ ] После выпуска проверить readiness, версии, ошибки/latency и последний успешный backup; при нарушении gate откатиться по процедуре T03/T06.

## 7. Что намеренно не включено в срочные исправления

- Переобучение модели, новый игровой контракт и объединение всех v8/v9/v10 в переписанное ядро.
- Redis, несколько NiceGUI-инстансов и полноценный monitoring stack без подтверждённой потребности.
- Автоматическое удаление production-аккаунтов, переписывание git history, массовая миграция всех LFS-артефактов.
- Скрытое изменение правил ожидания или сохранение abandoned drafts без отдельного продуктового решения.
- Глобальное шифрование storage «тем же секретом» как замена ограничениям доступа, retention и защите backup.

## 8. Статус подготовки плана

План составлен 2026-09-25 и дополнен отдельным этапом мобильного интерфейса и кросс-браузерности T15; всего 16 задач T00–T15. Реализация не начата; исходный код, модели, БД и deployment в этой сессии не изменялись. Для выполнения рекомендован последовательный проход небольшими PR/коммитами с проверками между задачами. Первое изменение — T01 после фиксации базы T00; настройки пула и workers идут только после наблюдаемости. Мобильный этап выполняется после T10 и до итоговой нагрузки T11.
