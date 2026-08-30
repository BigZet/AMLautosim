# PROJECT_AUDIT.md — независимая ревизия

**Дата:** 2026-08-30
**Ревизуемая версия:** `073a70b` «Externalize game configuration and preserve round settings» (ветка `master`)
**Метод:** чтение кода и документации, запуск существующих тестов, добавление собственных тестов, ручные проверки API и обоих интерфейсов в реальном браузере.
**Ограничения соблюдены:** существующий код, тесты и настройки не изменялись; дефекты не исправлялись. Добавлены только новые тесты (`tests/audit/`) и этот отчёт.

---

## 1. Резюме

| Приоритет | Кол-во | Суть |
| --- | ---: | --- |
| **P0 — блокирующий** | 1 | Обновление существующей установки навсегда роняет API: контейнер уходит в бесконечный рестарт, весь стек недоступен |
| **P1 — высокий** | 3 | Организатор видит максимум 100 из 500 участников; ники раскрываются без сессии; завершённый раунд пропадает у участника без сценария |
| **P2 — средний** | 7 | Сломанный CSS админки; перенос слов в кнопках на 1366×768; двойной учёт квоты; отсутствующая пагинация; отсутствующее логирование; сломанный skip в UI-тестах; лишний запрос на каждый rerun |
| **P3 — низкий** | 13 | Контраст, мёртвый код, расхождения документации и реализации, мелкие UX-дефекты |

**Что хорошо.** Доменное ядро сильное: правила и скоринг — чистые детерминированные функции на `Decimal`, снимок раунда неизменяем, инварианты вынесены в PostgreSQL (partial unique index на активный раунд, check-констрейнты, оптимистические ревизии, `FOR UPDATE NOWAIT` на скоринге). RBAC и изоляция участников работают корректно — проверено вручную. 409 существующих тестов проходят полностью.

**Главный риск.** Проект хрупок именно там, где обещает надёжность: при обновлении установки. Защитный механизм (заморозка снимка карточек) добавлен *после* разрушительного изменения (сокращения каталога), поэтому любая установка, прошедшая коммиты `a07bafb`/`a8fec3e` до `073a70b`, уже неработоспособна и не восстанавливается средствами приложения.

---

## 2. Как проводилась ревизия

### 2.1 Окружение

Локально доступен только Python 3.9, поэтому всё выполнялось в контейнерах на базе образа проекта (`python:3.13-slim` + `requirements.txt` + `pytest`, `anyio`, `ruff`, `playwright`).

| Что | Как |
| --- | --- |
| Существующие тесты | `docker run … aml-audit-test python -m pytest …` против PostgreSQL 16 из `docker-compose.yml` |
| Сборка | `docker compose build` + `docker compose up -d` |
| Ручные проверки API | `curl` к `127.0.0.1:8000` / `127.0.0.1:8010` |
| Интерфейс | Chromium (Playwright) + интерактивный браузер, эмуляция viewport, измерения через DOM |

### 2.2 Изменения в окружении (не в репозитории)

Ревизия обязана была пересобрать стек: работавшие контейнеры были собраны из рабочего дерева **до** последнего коммита (образ от 07:27 UTC, коммит в 12:32 UTC), поэтому проверять по ним ревизуемую версию нельзя. Пересборка выявила дефект **P0-1** и оставила основной стек в состоянии рестарт-петли — это и есть воспроизведение дефекта.

Что сделано с окружением:

1. `pg_dump -Fc` базы `aml_simulator` сохранён до всех действий: `…/scratchpad/aml_simulator_before_audit.dump`.
2. `docker compose build && docker compose up -d` — API не поднялся (см. P0-1). **Основной стек сейчас не работает; база и данные не пострадали.**
3. Для проверок интерфейса поднят изолированный стек на отдельной БД `aml_audit` и портах 8010/8511/8512 (контейнеры `aml-audit-api|play|admin`) — репозиторий и `docker-compose.yml` не затрагивались. Стек и база после ревизии удалены.
4. В изолированном стеке созданы учётные записи `audit.player@example.com`, участники `bulk0000…bulk0129` — только в удалённой базе `aml_audit`.
5. В основной базе `aml_simulator` создана одна учётная запись `audit.qa@example.com` (проверка формы регистрации до пересборки). Данные организатора и участника `123123123@mail.ru` не изменялись.

**Восстановление основного стека.** Ниже — исправление данных, а не кода: оно убирает из старого раунда ссылки на удалённые карточки, после чего seed успевает записать `card_snapshots`. **Проверено на копии базы** (восстановленный `pg_dump`, отдельная БД `aml_recovery_test`): seed завершается успешно, все данные целы (1 раунд, 3 пользователя, 1 сценарий, 5 версий, 1 результат), в раунд записывается снимок из 4 карточек.

```bash
docker exec amlautosim-db-1 psql -U aml -d aml_simulator -c "UPDATE rounds r SET game_config = jsonb_set(r.game_config, '{operations}', (SELECT jsonb_agg(op) FROM jsonb_array_elements(r.game_config->'operations') op WHERE (op->>'code', (op->>'version')::int) IN (SELECT code, version FROM action_cards))) WHERE r.game_config ? 'operations' AND NOT (r.game_config ? 'card_snapshots');" && docker compose up -d
```

Альтернатива — полный сброс с потерей демонстрационных данных:

```bash
docker compose down -v && docker compose up -d --build
```

Сохранённая копия базы до ревизии: `…/scratchpad/aml_simulator_before_audit.dump` (формат `pg_dump -Fc`).

---

## 3. Замечания

Формат: **приоритет · файл:строки · последствия · воспроизведение · исправление · проверка исправления**.
Раздел содержит только **факты** — воспроизведённое поведение. Гипотезы вынесены в §6, улучшения — в §7.

---

### P0-1 · API не стартует после обновления существующей установки

**Файлы:** [services/configuration.py:33-43](src/aml_workshop_simulator/services/configuration.py#L33-L43), [scripts/seed_database.py:87-97](scripts/seed_database.py#L87-L97), [docker-compose.yml:50-52](docker-compose.yml#L50-L52)

**Факт.** `seed_cards` при каждом старте API замораживает снимок карточек для **каждого существующего раунда**, используя карточки, которые остались в `action_cards` *на этот момент*:

```python
old_cards = list((await db.execute(select(ActionCard))).scalars().all())   # seed_database.py:87
rounds = list((await db.execute(select(Round).with_for_update())).scalars().all())
for round_obj in rounds:
    config = freeze_game_config(round_obj.game_config, old_cards)          # seed_database.py:90
```

`freeze_game_config` требует, чтобы каждая операция из `operations[]` нашлась среди этих карточек, иначе бросает исключение:

```python
if {spec.key for spec in specs} != pairs:
    raise ValueError("Cannot freeze round: a referenced card is missing")  # configuration.py:40
```

Коммит `a07bafb` («Reduce operation catalog to four actions») удалил из каталога `international` и `crypto_exchange`, а прежний seed удалил соответствующие строки `action_cards`. Защита в виде `card_snapshots` появилась только в `073a70b` — на два коммита позже. Раунд, созданный до сокращения каталога, содержит `operations` с шестью кодами и **не содержит** `card_snapshots`, поэтому заморозить его больше нечем.

**Последствия.** Команда контейнера — `sh -c "python -m scripts.seed_database … && uvicorn …"`. Seed завершается ненулевым кодом, `uvicorn` не запускается никогда. Контейнер `api` уходит в бесконечный рестарт; `play` и `admin` зависят от его healthcheck и не стартуют. **Весь стек недоступен, восстановление средствами приложения невозможно.** Замеренное состояние во время ревизии: `34 restarts, state=restarting`.

**Воспроизведение.**

```bash
docker exec amlautosim-db-1 psql -U aml -d aml_simulator -t -A -c "select jsonb_agg(x->>'code') from rounds, jsonb_array_elements(game_config::jsonb->'operations') x where id=1;"
# ["salary","cash_deposit","card_transfer","international","cash_withdrawal","crypto_exchange"]
docker compose up -d --build
docker compose logs api --tail 30
# ValueError: Cannot freeze round: a referenced card is missing
```

Модульное воспроизведение без БД: `tests/audit/test_upgrade_and_domain.py::test_freeze_game_config_rejects_a_round_that_references_a_removed_card`.

**Предлагаемое исправление.** Отсутствующая карточка исторического раунда не должна останавливать сервис. Варианты по возрастанию надёжности:

1. В `freeze_game_config` при вызове из seed пропускать раунд, который заморозить нельзя, и записывать причину в лог/аудит вместо исключения (строгую проверку оставить в `admin/common.validate_game_config`, где ошибка адресована организатору).
2. Дополнительно писать в снимок «надгробие» карточки (минимальный `CardSpec` из `operations[]`), чтобы завершённый раунд остался читаемым.
3. Отделить seed от старта: `uvicorn` не должен зависеть от успеха seed; миграции и seed — отдельный job или entrypoint c явным флагом «ошибка seed не блокирует сервис для уже существующих раундов».

**Проверка исправления.** `tests/audit/test_upgrade_and_domain.py::test_freeze_game_config_rejects_a_round_that_references_a_removed_card` должен упасть (это ожидаемый сигнал). Плюс новый интеграционный тест: создать раунд, удалить карточку из `action_cards`, вызвать `seed()` — функция обязана завершиться успешно, а раунд остаться читаемым через `GET /api/v1/admin/rounds/{id}`.

---

### P1-1 · Организатор не может увидеть больше 100 участников

**Файл:** [api/routers/admin/participants.py:59-126](src/aml_workshop_simulator/api/routers/admin/participants.py#L59-L126) (`limit` — строка 66, обрезание — строки 124-125, `next_cursor=None` — строка 126)

**Факт.** `limit: int = Query(default=100, ge=1, le=100)` — жёсткий потолок 100. `next_cursor` всегда `None`, курсор не принимается. Обрезание выполняется в Python **после** выборки всех строк из БД, поэтому SQL всё равно тянет всех участников.

**Последствия.** Документация (`docs/README.md`, `docs/security.md`) рассчитывает систему на аудиторию **до 500 участников**. Организатор физически не может открыть карточку 101-го участника, снять блокировку или посмотреть его черновики: клиент админки (`ui/shared/api_client.py:486-504`) даже не передаёт `limit`. Поиск по имени/email частично спасает, но только если организатор заранее знает, кого искать.

**Воспроизведение.** `tests/audit/test_api_surface.py::test_admin_participant_list_is_capped_at_100_rows_without_a_cursor` — создаёт 130 участников, получает ровно 100 строк и `next_cursor: null`; `limit=200` отвергается с 422.

**Предлагаемое исправление.** Реализовать курсорную постраничность, обещанную схемой `PlayerSummaryPageOut.next_cursor`: keyset-пагинация по `User.id`, `.limit(limit + 1)` в SQL, возврат непрозрачного курсора; в админке — кнопка «Показать ещё» либо `st.dataframe` со всей выборкой.

**Проверка исправления.** Тест выше должен упасть на строке `assert len(payload["rows"]) == 100`. Дополнительно: пройти по курсору до конца при 130 участниках и убедиться, что объединение страниц равно полному множеству без повторов.

---

### P1-2 · `?reveal=true` раскрывает настоящие ники без сессии и без роли ведущего

**Файл:** [api/routers/rounds.py:853-907](src/aml_workshop_simulator/api/routers/rounds.py#L853-L907) (параметр — строка 861, применение — строки 892-895)

**Факт.** `reveal` — обычный query-параметр без какой-либо авторизации. Зависимость `get_principal_optional` допускает анонимный вызов, и её результат используется только для флага `is_current_user`. Проверено напрямую:

```bash
curl -s "http://127.0.0.1:8000/api/v1/rounds/1/leaderboard?reveal=true"
# {"rows":[{"rank":1,"display_name":"123123123","masked":false, …}]}   ← без X-Session-ID
```

**Расхождение с документацией.** `docs/security.md` §13: «ники на общем экране скрыты по умолчанию и раскрываются только явной командой **ведущего**». `docs/scoring-and-leaderboard.md` §«Скрытые ники»: «пока **ведущий** не нажмет "Показать все ники"». В реализации кнопка «Показать все ники» находится в интерфейсе **участника** ([ui/participant/app.py:1455-1459](src/aml_workshop_simulator/ui/participant/app.py#L1455-L1459)), а API не различает вызывающего вообще.

**Последствия.** Заявленная мера защиты школьников («провокационный ник на проекторе») не работает: любой участник раскрывает список всех ников одним нажатием, а любой, кто дотянулся до API, — без входа. В поставляемом compose API опубликован только на `127.0.0.1`, что снижает, но не устраняет риск: участник раскрывает ники штатной кнопкой.

**Воспроизведение.** `tests/audit/test_api_surface.py::test_reveal_true_returns_real_nicknames_to_an_anonymous_caller` и `::test_any_participant_can_reveal_every_nickname`.

**Предлагаемое исправление.** Принять решение и синхронизировать код с документацией:
* либо `reveal=true` требует `get_current_admin` (а участник видит только свою строку раскрытой) — соответствует нынешнему тексту документации;
* либо документацию привести в соответствие с реализацией и признать раскрытие общедоступным.
В любом случае `get_principal_optional` заменить на явную проверку, а факт раскрытия писать в `audit_events`.

**Проверка исправления.** Тесты выше должны упасть; добавить тест «участник получает 403 на `reveal=true`, администратор — 200».

---

### P1-3 · Завершённый раунд исчезает у участника, не успевшего сохранить черновик

**Файл:** [api/routers/rounds.py:274-341](src/aml_workshop_simulator/api/routers/rounds.py#L274-L341)

**Факт.** `GET /rounds/mine` перечисляет: (а) текущий раунд в статусе `active`/`stopped`/`scoring` и (б) раунды, в которых у участника есть строка `scenarios`. Завершённый раунд без сценария участника не попадает ни в одну категорию.

Страницы «Результат» ([app.py:1377-1381](src/aml_workshop_simulator/ui/participant/app.py#L1377-L1381)) и «Лидерборд» ([app.py:1439-1442](src/aml_workshop_simulator/ui/participant/app.py#L1439-L1442)) строят выпадающий список раундов именно из `/rounds/mine`.

**Последствия.** Участник, который вошёл, но не успел сохранить ни одного черновика (реалистично на 45-минутном мастер-классе), после завершения раунда видит «Раундов пока нет» и не может посмотреть публичный лидерборд, хотя тот существует и заполнен. Наблюдалось вживую в интерфейсе до пересборки стека.

**Воспроизведение.** `tests/audit/test_api_surface.py::test_completed_round_disappears_for_a_participant_without_a_scenario`. Вручную: зарегистрировать участника после завершения раунда, открыть «Лидерборд».

**Предлагаемое исправление.** Включить в `/rounds/mine` последний завершённый раунд независимо от наличия сценария (со `scenario_status = None`), либо дать страницам «Результат»/«Лидерборд» отдельный источник — например `GET /rounds/current`, который уже возвращает завершённый раунд.

**Проверка исправления.** Тест выше должен упасть на `assert mine.json()["rows"] == []`.

---

### P2-1 · В админке не существует трёх CSS-переменных: пропали границы таблиц и иерархия заголовков

**Файл:** [ui/admin/app.py:47-95](src/aml_workshop_simulator/ui/admin/app.py#L47-L95) (строки 50, 51, 55)

**Факт.** Стили админки построены на переменных, которых Streamlit не публикует:

```css
--aml-line: var(--border-color);                                     /* app.py:50 */
--aml-muted: color-mix(in srgb, var(--text-color) 62%, transparent); /* app.py:51 */
.aml-kicker { color: var(--primary-color); }                         /* app.py:55 */
```

Измерено в браузере на странице «Участники» (тёмная тема, Chromium):

| Селектор | Ожидалось | Фактически |
| --- | --- | --- |
| `--primary-color`, `--text-color`, `--border-color` | цвета темы | `""` (пусто) |
| `table.aml-table th` `border-bottom` | `1px solid` линия | `0px none` — **разделителей строк нет** |
| `table.aml-table td` `border-bottom` | `1px solid` | `0px none` |
| `.aml-pill` `border` | `1px solid` | `0px none` — **у «пилюль» нет контура** |
| `.aml-kicker` / `.aml-subtitle` / `.aml-title` | акцент / приглушённый / основной | все три `rgb(232, 239, 236)` — **иерархия схлопнута** |

Интерфейс участника той же проблемы не имеет: он объявляет `--aml-line: rgba(127,127,127,.28)` литералом ([ui/participant/app.py:52](src/aml_workshop_simulator/ui/participant/app.py#L52)).

**Последствия.** Все таблицы админки (участники, версии черновиков, сессии, лидерборд, аудит) отображаются без разделителей строк — при 100 строках читать их тяжело. Подзаголовок неотличим от заголовка, надзаголовок — от обычного текста. Дефект воспроизводится на **всех** проверенных размерах окна и в обеих темах.

**Воспроизведение.** Открыть админку → «Участники», в консоли браузера:

```js
getComputedStyle(document.querySelector('table.aml-table th')).borderBottomWidth  // "0px"
getComputedStyle(document.documentElement).getPropertyValue('--primary-color')     // ""
```

**Предлагаемое исправление.** Объявить палитру литералами, как в интерфейсе участника, либо через `var(--border-color, rgba(127,127,127,.28))` с рабочим fallback. Значения темы задаются в `.streamlit/config.toml` и доступны в Python через `st.get_option("theme.borderColor")` — их можно подставить в строку стилей на сервере.

**Проверка исправления.** Тот же фрагмент в консоли должен вернуть `"1px"`. Автоматически — через существующий Playwright-набор: добавить проверку `border-bottom-width` у `table.aml-table th`.

---

### P2-2 · Кнопки шага цепочки ломаются посреди слова на типичных ноутбучных разрешениях

**Файл:** [ui/participant/app.py:1005-1031](src/aml_workshop_simulator/ui/participant/app.py#L1005-L1031) (`st.columns(4)` — строка 1005) и медиазапросы [app.py:128-168](src/aml_workshop_simulator/ui/participant/app.py#L128-L168)

**Факт.** Четыре кнопки («Вверх», «Вниз», «Дублировать», «Удалить») размещены в четырёх равных колонках внутри правой колонки рабочей области. Медиазапрос `@media (max-width: 1100px)` перестраивает горизонтальные блоки, но диапазон 1101…~1500 px остаётся без правил, и ширины колонки не хватает.

Измерено (высота подписи / высота строки; полные измерения — `tests/artifacts/audit-2026-08-30/layout-measurements.json`):

| Размер окна | Результат |
| --- | --- |
| 1920×1080 | чисто |
| **1366×768** | «Дублировать» — **2 строки**, перенос посреди слова, в каждой карточке шага |
| **1101×800** | «Вверх» / «Удалить» — 2 строки, **«Дублировать» — 4 строки** («Дуб лир оват ь»), «Сохранить черновик» и «Отправить сценарий» — по 2 строки; селектор «Канал» обрезан («Банковское зачи…») |
| 1099×800 | чисто (сработал медиазапрос — кнопки становятся вертикальными) |
| 768×1024, 641×900, 639×900, 390×844, 360×800 | чисто |

**Последствия.** 1366×768 — самое распространённое разрешение ноутбука; на нём основной рабочий элемент интерфейса выглядит сломанным. Горизонтальной прокрутки страницы не возникает ни на одном размере — то есть дефект чисто визуальный, но заметен всем участникам с таким экраном.

**Воспроизведение.** Скриншоты: `tests/artifacts/audit-2026-08-30/participant-builder-1101x800.png`, `…-1366x768.png`. Программно — фрагмент из `layout-measurements.json`.

**Предлагаемое исправление.** Раздвинуть медиазапрос до ширины, при которой четыре подписи помещаются (порядка `max-width: 1500px`), либо задать `white-space: nowrap` кнопкам шага и перевести их в 2×2, либо заменить подписи иконками с `title`/`help`.

**Проверка исправления.** Повторить измерение (скрипт лежит в `layout-measurements.json`) на 1101 и 1366: список `wrappedButtons` должен быть пуст.

---

### P2-3 · Квота «anonymous» учитывается дважды

**Файл:** [domain/rules.py:943-949](src/aml_workshop_simulator/domain/rules.py#L943-L949)

**Факт.**

```python
if spec.quota_category:
    quota_usage[spec.quota_category] = money(quota_usage[spec.quota_category] + gross)
if recipient_type == "anonymous_wallet":
    quota_usage["anonymous"] = money(quota_usage["anonymous"] + gross)
```

Для карточки с `quota_category = "anonymous"` и шагом на анонимный кошелёк один и тот же `gross` прибавляется к квоте `anonymous` дважды.

**Последствия.** Латентный дефект: в поставляемом `config/operations.json` карточек с `quota_category = "anonymous"` нет, поэтому сейчас не проявляется. Схема его допускает — `CardConfig.quota_category: Literal["cash", "anonymous"] | None` ([schemas/catalog_config.py:70](src/aml_workshop_simulator/schemas/catalog_config.py#L70)). Появление такой карточки даст участнику ложное нарушение `category_limit_exceeded` при половине заявленного лимита.

**Воспроизведение.** `tests/audit/test_upgrade_and_domain.py::test_anonymous_quota_is_counted_twice_for_an_anonymous_category_card` — фиксирует `20000.00` там, где ожидается `10000.00`.

**Предлагаемое исправление.** Прибавлять к квоте `anonymous` по признаку получателя только если `spec.quota_category != "anonymous"`, либо собрать множество применимых квот шага и прибавлять `gross` один раз на квоту.

**Проверка исправления.** Тест выше должен упасть; парный контрольный тест `::test_anonymous_quota_is_counted_once_when_the_card_has_no_category` обязан продолжать проходить.

---

### P2-4 · Постраничность задокументирована, но не реализована ни в одном endpoint

**Файлы:** [rounds.py:341](src/aml_workshop_simulator/api/routers/rounds.py#L341), [rounds.py:905-907](src/aml_workshop_simulator/api/routers/rounds.py#L905-L907), [admin/participants.py:126](src/aml_workshop_simulator/api/routers/admin/participants.py#L126), [admin/audit.py:57](src/aml_workshop_simulator/api/routers/admin/audit.py#L57), [admin/leaderboard.py:286](src/aml_workshop_simulator/api/routers/admin/leaderboard.py#L286)

**Факт.** Все пять endpoint'ов возвращают `next_cursor=None` безусловно. Параметр `cursor`, задокументированный в `docs/api.md:275` (`GET /api/v1/rounds/mine?limit=10&cursor=...`), в обработчиках не объявлен и молча игнорируется:

```bash
curl -s "http://127.0.0.1:8000/api/v1/rounds/mine?limit=10&cursor=abc" -H "X-Session-ID: …"
# 200 OK, "next_cursor": null — курсор не влияет ни на что
```

**Последствия.** Прямая причина P1-1. Для аудита раунда — потолок 200 событий (`admin/audit.py:26`), для лидерборда участника — 200 строк; при 500 участниках нижняя часть таблицы недостижима.

**Воспроизведение.** `tests/audit/test_api_surface.py::test_documented_cursor_parameter_is_ignored_by_rounds_mine`.

**Предлагаемое исправление.** Реализовать keyset-пагинацию хотя бы для `/admin/rounds/{id}/participants` и `/rounds/{id}/leaderboard`; для остальных — убрать `next_cursor` из схем и `cursor` из `docs/api.md`, чтобы контракт не обещал несуществующего.

**Проверка исправления.** Тест выше должен упасть; добавить тест обхода по курсору на 130 участниках.

---

### P2-5 · Структурированное логирование описано в документации, но не реализовано

**Файлы:** [api/main.py:29](src/aml_workshop_simulator/api/main.py#L29), весь `src/`; спецификация — `docs/operations.md` §7-8

**Факт.** В `src/` нет ни одного `import logging` и ни одного вызова логгера:

```bash
grep -rn "import logging\|logger\." --include="*.py" src/   # пусто
```

`SENSITIVE_HEADERS = {"x-session-id", "authorization", "cookie"}` объявлено в `api/main.py:29` и **нигде не используется** — заготовка редактирования логов без самих логов.

`docs/operations.md` §7 описывает обязательные поля события, перечень событий (`scenario_saved`, `round_activated`, `round_scored`, `participant_blocked`, …) и запрещённые к логированию поля; §8 — сквозную корреляцию `X-Request-ID`. Реализована только половина корреляции: middleware генерирует и возвращает `X-Request-ID` ([api/main.py:32-39](src/aml_workshop_simulator/api/main.py#L32-L39)), но никуда его не пишет. Мониторинговые пороги из §6 (5xx rate, p95 latency, DB pool) без логов и метрик недостижимы.

**Последствия.** На мероприятии диагностика ограничена access-логом uvicorn. Ошибка 500 отдаёт участнику `request_id`, по которому на сервере ничего нельзя найти. Меры «Structured allowlist logging and redaction» из матрицы угроз `docs/security.md` §3 фактически отсутствуют.

**Воспроизведение.** `grep` выше; `docker compose logs api` содержит только строки uvicorn.

**Предлагаемое исправление.** Добавить JSON-форматтер, middleware `request_completed` (маршрут, метод, статус, `latency_ms`, `request_id`) и вызовы на доменных событиях, уже отражаемых в `audit_events`. `SENSITIVE_HEADERS` использовать в редакторе или удалить.

**Проверка исправления.** Тест, который делает запрос и проверяет, что в лог попала строка JSON с `request_id` из заголовка ответа и без `email` / `X-Session-ID` (в `docs/testing-strategy.md` такая проверка уже заявлена как «Automated log scan»).

---

### P2-6 · `pytest.importorskip` в Playwright-тестах стоит после импорта, который падает

**Файлы:** [tests/ui/test_playwright_admin.py:20-37](tests/ui/test_playwright_admin.py#L20-L37), [tests/ui/test_playwright_participant.py:23-45](tests/ui/test_playwright_participant.py#L23-L45), [tests/ui/streamlit_driver.py:13](tests/ui/streamlit_driver.py#L13)

**Факт.** `from tests.ui.streamlit_driver import (…)` (строка 20 / 23) выполняется раньше, чем `pytest.importorskip("playwright.sync_api")` (строка 37 / 45), а `streamlit_driver.py:13` импортирует `playwright.sync_api` без защиты. Guard недостижим. Selenium-наборы сделаны правильно: `importorskip` там стоит **до** импорта драйвера (`test_selenium_flows.py:45`, `test_selenium_auth.py:29`, с `# noqa: E402`).

**Последствия.** `tests/README.md` обещает: «Если браузер недоступен, соответствующие наборы помечаются как skipped, а не падают». Фактически при отсутствии пакета `playwright` сбор прерывает **всю** сессию pytest:

```
ERROR tests/ui/test_playwright_admin.py … ModuleNotFoundError: No module named 'playwright'
!!!!! Interrupted: 2 errors during collection !!!!!
4 tests collected, 2 errors in 0.13s
```

То есть `python -m pytest` в корне репозитория не выдаёт вообще никаких результатов, а не частичные.

**Воспроизведение.** Запустить `python -m pytest tests/ui -q` в окружении без `playwright` (например, в образе, собранном только по `requirements.txt`).

**Предлагаемое исправление.** Перенести `pytest.importorskip("playwright.sync_api")` выше импорта `streamlit_driver`, с `# noqa: E402` на последующих импортах — ровно как сделано в Selenium-наборах.

**Проверка исправления.** Тот же запуск должен дать `skipped`, а не `errors`, и не прерывать сессию.

---

### P2-7 · Конструктор делает лишний запрос к API на каждый rerun

**Файл:** [ui/participant/app.py:859-860](src/aml_workshop_simulator/ui/participant/app.py#L859-L860), кэш — [app.py:308-339](src/aml_workshop_simulator/ui/participant/app.py#L308-L339)

**Факт.** Кандидат для кнопки «Добавить в цепочку» получает новый идентификатор при каждом прогоне скрипта:

```python
candidate = {**step, "step_id": str(uuid.uuid4())}                       # app.py:859
candidate_preview = preview(client, round_id, session_id, [*steps, candidate])
```

Ключ мемоизации — `json.dumps([round_id, steps])` ([app.py:317-319](src/aml_workshop_simulator/ui/participant/app.py#L317-L319)) — включает `step_id`, поэтому попадание в кэш для кандидата **невозможно**: каждый rerun даёт новый ключ. Кэш при этом растёт и целиком сбрасывается на 32 записях, обесценивая и попадания для основной цепочки.

**Измерено** (access-лог API, изолированный стек, цепочка из 3 шагов): **2 × `POST /scenario/preview` на каждый рендер конструктора** — один для сохранённой цепочки, один для кандидата, который никогда не кэшируется. Полный рендер страницы стоит ≈7 обращений к API:

```
2 × POST /rounds/2/scenario/preview
1 × GET  /rounds/current
1 × GET  /auth/session
1 × GET  /rounds/2/cards
1 × GET  /rounds/2/scenario
1 × GET  /rounds/2/scenario/versions
```

**Последствия.** `POST /preview` — самый дорогой read-запрос: он загружает карточки раунда, строит политику и полностью прогоняет `evaluate_scenario`. Наполовину эта нагрузка бесполезна. При аудитории, ради которой система проектировалась, это удвоение самой тяжёлой операции.

**Воспроизведение.** `docker logs <api> | grep -c "scenario/preview"` до и после трёх перезагрузок страницы конструктора: прирост 6.

**Предлагаемое исправление.** Держать `step_id` кандидата стабильным в `st.session_state` до фактического добавления шага (генерировать новый только в обработчике кнопки), либо исключить `step_id` из ключа кэша.

**Проверка исправления.** Тот же счётчик: 1 запрос `preview` на рендер вместо 2.

---

### P3 · Прочие замечания

| № | Приоритет | Файл:строки | Замечание | Последствия | Исправление |
| --- | --- | --- | --- | --- | --- |
| P3-1 | Низкий | [ui/participant/app.py:51,65-66](src/aml_workshop_simulator/ui/participant/app.py#L51-L66) | Контраст `.aml-kicker` (`#13836f`, 12 px, 700) — **3.96:1** на тёмной теме и **4.33:1** на светлой (измерено в браузере). Порог WCAG AA для 12 px bold — 4.5:1 | Надзаголовок трудночитаем; интерфейс участника жёстко зашивает светлый акцент `#13836f`, игнорируя `primaryColor = #4CC7AB` из `.streamlit/config.toml` для тёмной темы | Взять акцент из темы Streamlit либо задать отдельное значение для тёмной темы через `@media (prefers-color-scheme: dark)` |
| P3-2 | Низкий | [db/repositories/users.py:4](src/aml_workshop_simulator/db/repositories/users.py#L4) | `from …schemas.auth import UserCreate` — класса `UserCreate` не существует. Модуль ниоткуда не импортируется, поэтому `ImportError` не проявляется | Мёртвый и нерабочий код: `UserRepository`, `ScenarioRepository`, `RoundRepository` не используются нигде (`grep` подтверждает) | Удалить каталог `db/repositories/` целиком |
| P3-3 | Низкий | [core/enums.py](src/aml_workshop_simulator/core/enums.py), [admin/common.py:33-39](src/aml_workshop_simulator/api/routers/admin/common.py#L33-L39) | `RoundStatus` и `ScenarioStatus` нигде не используются (статусы — обычные строки), при этом `RoundStatus` **не содержит** `stopped`, который есть в БД и в коде. `ROUND_TRANSITIONS` объявлен и не используется | Расхождение между «схемой состояний» в комментариях и реальными переходами; риск, что кто-то начнёт полагаться на неполный enum | Удалить неиспользуемое либо начать применять и добавить `stopped` |
| P3-4 | Низкий | [ui/admin/config_editor.py:108-109](src/aml_workshop_simulator/ui/admin/config_editor.py#L108-L109) | `_number` всегда вызывает `st.number_input(value=float(value))`, поэтому целочисленные настройки показываются как «14,00», «18,00», «8,00», «2,00» | Организатор видит копейки у «Энергии» и «Максимума операций»; значение затем приводится к `int()`, так что функционально безвредно | Передавать `int` для целочисленных полей — Streamlit сам выберет целочисленный виджет |
| P3-5 | Низкий | [core/config.py:17](src/aml_workshop_simulator/core/config.py#L17), [.env.example](.env.example) | `docs/security.md:92`: «После **пяти** неудачных попыток account временно блокируется». Код и `.env.example`: `LOGIN_MAX_FAILED_ATTEMPTS = 10` | Заявленная политика безопасности вдвое строже поставляемой | Согласовать значение с документом |
| P3-6 | Низкий | [ui/admin/app.py:319-361](src/aml_workshop_simulator/ui/admin/app.py#L319-L361) | Кнопка «Начать раунд» показывается только при `status == "draft"`, хотя API разрешает запуск остановленного раунда ([admin/rounds.py:273-281](src/aml_workshop_simulator/api/routers/admin/rounds.py#L273-L281)) | Организатор, случайно остановивший раунд, не может возобновить его из интерфейса — только «Перезапустить», что создаёт новый раунд и оставляет участников без их цепочек | Показывать «Начать раунд» также при `status == "stopped"` |
| P3-7 | Низкий | [ui/participant/app.py:1414-1425](src/aml_workshop_simulator/ui/participant/app.py#L1414-L1425) | Факторы риска выводятся без привязки к шагу, хотя `step_id` есть в объяснении | Наблюдалось: два фактора с одинаковым текстом «Крупные суммы повышают приоритет проверки» (+6.00 и +5.00) выглядят как дубликат — учебная ценность разбора теряется | Показывать номер и название шага рядом с фактором |
| P3-8 | Низкий | нет `pyproject.toml`, нет `.github/` | `ruff` объявлен в `requirements-dev.txt`, но конфигурации нет и CI нет. `ruff check src` (ruff 0.16.5, настройки по умолчанию) даёт **148 замечаний**, `--select E,F` — **166 × E501** | Линтер не защищает ничего; при первом включении в CI сборка упадёт. Основная масса — 83 × B008 (ложные срабатывания на `Depends()` FastAPI), 17 × I001, 16 × UP045 | Добавить `[tool.ruff]` с `per-file-ignores` для `B008` в роутерах и минимальный CI-workflow |
| P3-9 | Низкий | [scripts/seed_database.py:155-173](scripts/seed_database.py#L155-L173) | `seed_admin` создаёт администратора, но никогда не обновляет его пароль | Изменение `BOOTSTRAP_ADMIN_PASSWORD` в `.env` после первого запуска не действует; `.env.example` при этом просит «Change it from any value that has ever been committed» | Либо обновлять хеш при изменении переменной, либо явно задокументировать это в `.env.example` и `docs/deployment.md` |
| P3-10 | Низкий | [ui/participant/app.py:889-890](src/aml_workshop_simulator/ui/participant/app.py#L889-L890) | `st.session_state[draft_key] = default_step(card)` после добавления шага не сбрасывает форму: виджеты со стабильными ключами сохраняют значение | Наблюдалось: после добавления шага на 120 000 ₽ конструктор продолжает показывать 120 000 ₽, хотя код рассчитывает на сброс к минимуму | Либо удалять ключи виджетов `builder_*`, либо убрать бесполезное присваивание |
| P3-11 | Низкий | [docker-compose.yml:80-81,104-105](docker-compose.yml#L80-L105) | Streamlit публикуется на `0.0.0.0` по HTTP; обратного прокси в compose нет. Заголовки из `docs/security.md` §8 (HSTS, `X-Content-Type-Options`, CSP, `Referrer-Policy`, `X-Frame-Options`) отсутствуют — проверено `curl -D -` | При запуске «по README» на площадке cookie идут по открытому Wi-Fi с `COOKIE_SECURE=false`. `README.md` отсылает к `docs/deployment.md`, поэтому это скорее незакрытая эксплуатационная предпосылка, чем дефект кода | Добавить в README явное предупреждение «compose — только для локального запуска» и/или профиль compose с прокси |
| P3-12 | Низкий | [ui/participant/app.py:1122-1127,1177-1182](src/aml_workshop_simulator/ui/participant/app.py#L1122-L1182) | На 360×800 и 390×844 таблицы «Квоты и лимиты» и «История черновиков» выходят за пределы контейнера (`limits-table`, `versions-table`) и прокручиваются внутри `.aml-scroll` — прокрутки страницы не возникает, но признака прокрутки нет | Колонка «Статус» истории и часть «Без нарушений» просто не видны; участник не догадывается провести пальцем | Добавить градиент-подсказку у края или перевести таблицы в карточки на узких экранах |
| P3-13 | Низкий | [api/routers/health.py:15-36](src/aml_workshop_simulator/api/routers/health.py#L15-L36) | `MIGRATIONS_DIR` вычисляется от `__file__` через `parents[4]`. Если каталог не найден, `_expected_heads()` вернёт пустое множество, а проверка `if expected and applied != expected` его пропустит | `/health/ready` отрапортует `"migrations": "head"`, не проверив ничего. В текущем Docker-образе путь корректен; риск возникает при установке пакета в `site-packages` | Сравнивать с `ScriptDirectory.from_config(...).get_heads()` из Alembic либо падать при отсутствии каталога |

---

## 4. Интерфейс: матрица размеров окна

Chromium, эмуляция viewport, тёмная тема. Полноэкранные скриншоты — `tests/artifacts/audit-2026-08-30/` (каталог в `.gitignore`, поэтому в коммит не входит); измерения — `layout-measurements.json` там же.

Проверялись: горизонтальная прокрутка страницы, обрезание текста (`scrollWidth > clientWidth` вне прокручиваемых контейнеров), выход элементов за правый край viewport, перенос подписей кнопок на несколько строк.

### 4.1 Конструктор сценария (цепочка из 3 шагов, черновик)

| Размер | Скриншот | Прокрутка страницы | Результат |
| --- | --- | --- | --- |
| 360×800 | `participant-builder-360x800.png` | нет | Чисто. Таблицы прокручиваются внутри `.aml-scroll` (P3-12) |
| 390×844 | `participant-builder-390x844.png` | нет | То же |
| 639×900 | `participant-builder-639x900.png` | нет | Чисто (граница медиазапроса 640 px) |
| 641×900 | `participant-builder-641x900.png` | нет | Чисто |
| 768×1024 | `participant-builder-768x1024.png` | нет | Чисто, сайдбар корректно свёрнут (`x = -300`, ширина 0) |
| 1099×800 | `participant-builder-1099x800.png` | нет | Чисто; плитки ресурсов уходят в один столбец — страница становится высокой |
| **1101×800** | `participant-builder-1101x800.png` | нет | **11 кнопок переносятся; «Дублировать» — 4 строки; селектор «Канал» обрезан** (P2-2) |
| **1366×768** | `participant-builder-1366x768.png` | нет | **«Дублировать» — 2 строки в каждой карточке шага** (P2-2) |
| 1920×1080 | `participant-builder-1920x1080.png` | нет | Чисто |

### 4.2 Админка, «Раунд и конфигурация»

| Размер | Скриншот | Результат |
| --- | --- | --- |
| 360×800 … 1920×1080 (все 9) | `admin-round-*.png` | Раскладка чистая на всех размерах: ни горизонтальной прокрутки, ни переносов, ни обрезаний. Единственное — обрезание длинных ключей внутри диагностического `st.json` на 360/390, это собственный виджет Streamlit в свёрнутом экспандере |
| 1101×800 | `admin-round-1101x800.png` | Подпись «Цель: расходный оборот, ₽» переносится на 2 строки, из-за чего первое поле ряда смещено вниз относительно трёх соседних — косметика |
| Все размеры | — | Границы таблиц отсутствуют, иерархия заголовков схлопнута (P2-1) |

### 4.3 Проверенные сценарии интерфейса

| Сценарий | Результат |
| --- | --- |
| Регистрация участника, локальная валидация пароля | OK — «Пароль должен содержать не менее 10 символов» до отправки запроса |
| Вход участника, восстановление сессии из cookie | OK |
| Экран ожидания при раунде в статусе `draft` | OK |
| Добавление шага, пересчёт ресурсов до сохранения | OK — «Влияние операции» и метрики совпадают с расчётом сервера |
| Сохранение черновика, история версий | OK |
| Отправка сценария, блокировка редактирования | OK |
| Запуск раунда организатором | OK |
| Скоринг раунда с подтверждением | OK — «оценено 1 сценариев за 4 мс» |
| Страница «Результат», разбор факторов | OK, замечание P3-7 |
| Лидерборд: маскировка по умолчанию, «· вы», раскрытие | OK по механике, замечание P1-2 по правам |
| Инспектор участника: сценарий, версии, сессии, доступ | OK |
| Перезапуск раунда с активацией | OK — создан раунд #2, раунд #1 сохранён |

---

## 5. Результаты выполненных проверок

| Проверка | Команда | Результат |
| --- | --- | --- |
| Unit-тесты | `pytest tests/unit -q` | **156 passed**, 1.7 с |
| Integration + contract | `pytest tests/integration tests/contract -q` | **253 passed**, 2 warnings, 5 мин 27 с |
| Добавленные тесты ревизии | `pytest tests/audit -q` | **10 passed**, 5.6 с |
| **Итого** | | **419 passed, 0 failed** |
| UI-наборы | `pytest tests/ui --collect-only` | **2 errors** — Playwright-модули не собираются (P2-6); Selenium корректно `skipped` |
| E2E | `pytest tests/e2e --collect-only` | Собирается; выполнение требует docker-in-docker (не проверялось, §8) |
| Сборка образов | `docker compose build` | **Успешно**, три образа |
| Запуск на чистой БД | миграции + seed + uvicorn | **Успешно**: 4 миграции, `cards=4 admin_id=1 round_id=1 status=draft`, `/health/ready` → 200 |
| Запуск на существующей БД | `docker compose up -d` | **Провал** — P0-1, 34 рестарта |
| Линтер | `ruff check src` | 148 замечаний (по умолчанию), 166 × E501 при `--select E,F` |
| RBAC | 8 admin-endpoint'ов без сессии и с сессией участника | Корректно: **401** без сессии, **403** с сессией участника |
| Изоляция сценариев | участник читает `/rounds/1/scenario` | Возвращает `null`, чужой сценарий недоступен |
| Разделение audiences | play-сессия к `/admin/rounds` | **403** |
| Инварианты БД | `\d+ rounds` | `uq_rounds_single_active` (partial unique), `ck_rounds_status` со всеми пятью статусами, FK и индексы на месте |
| Гигиена репозитория | `git ls-files` | Секреты не отслеживаются, `.env` никогда не коммитился, `tests/artifacts/` и `.backups/` в `.gitignore` |
| Приватность лидерборда | `curl` без сессии, с `reveal=true` | **Ники раскрываются** — P1-2 |

### 5.1 Зависимости

`requirements.txt` использует нижние границы (`>=`) для всех пакетов, кроме `bcrypt==3.2.2`. Lock-файла нет.

* **Факт:** воспроизводимость сборки не гарантирована — два `docker compose build` в разные дни дадут разные версии `fastapi`, `sqlalchemy`, `streamlit`, `pydantic`. Для `streamlit>=1.62` это существенно: интерфейсы опираются на `st.navigation`, `st.fragment`, `st.context.headers`, `st.context.ip_address` и на внутренние `data-testid` Streamlit.
* **Факт:** `docs/security.md` §3 требует «Pinned lock, image scan, minimal image, provenance» как меру против компрометации зависимостей — не выполнено.
* `bcrypt==3.2.2` закреплён жёстко (известная несовместимость `passlib` с bcrypt ≥ 4 — обоснованно).
* Уязвимых версий не выявлено, но и проверить нечего: без lock-файла состав образа не детерминирован.

**Рекомендация.** Зафиксировать `requirements.lock` через `pip-compile`/`uv lock` и собирать образ из него.

---

## 6. Гипотезы (требуют подтверждения)

Отделено от фактов сознательно: ниже — то, что следует из кода, но не воспроизведено в живом сценарии.

1. **Редактор админки может собрать веса ресурсов, которые API отвергнет.**
   `_number` ([config_editor.py:108](src/aml_workshop_simulator/ui/admin/config_editor.py#L108)) работает через `float` и сериализует веса как `str(float)`, а собственная проверка допускает погрешность `1e-9` ([config_editor.py:422](src/aml_workshop_simulator/ui/admin/config_editor.py#L422)). Сервер сравнивает сумму точным `Decimal` ([round_config.py:266](src/aml_workshop_simulator/schemas/round_config.py#L266)).
   *Подтверждено:* сервер действительно требует точного равенства — `tests/audit/test_upgrade_and_domain.py::test_resource_weights_must_sum_to_exactly_one`, значение `0.30000000000000004` отвергается.
   *Не подтверждено:* что виджет Streamlit при шаге 0.05 реально выдаёт такое значение — Streamlit округляет по `format`, и в проверенных состояниях сумма была ровно 1.00. Проверить: пройти шагом «+»/«−» по каждому из пяти весов и сохранить конфигурацию.

2. **Ёмкости может не хватить на 500 участников.** Замерено 7 обращений к API на один полный рендер конструктора, из них 2 — тяжёлый `POST /preview` (P2-7). Нагрузочный тест, требуемый `docs/operations.md` §2 как release gate, не проводился — вывод о ёмкости сделать нельзя.

3. **После перезапуска без активации участники продолжают видеть остановленный раунд.** `GET /rounds/current` ([rounds.py:255-260](src/aml_workshop_simulator/api/routers/rounds.py#L255-L260)) отдаёт `stopped` раньше, чем `draft`, поэтому конструктор покажет старый раунд, а не экран ожидания нового. Возможно, это осознанное решение (участник видит свою цепочку); в `docs/workshop-flow.md` явного ответа нет.

---

## 7. Улучшения (не дефекты)

1. **Пакет не устанавливаемый.** Нет `pyproject.toml`; импорты держатся на правке `sys.path` в двух приложениях Streamlit и `prepend_sys_path = .` в `alembic.ini`. Это работает в Docker, но мешает `pip install -e .`, IDE и типизации.
2. **Абсолютные импорты вида `src.aml_workshop_simulator.…`** привязывают код к имени каталога `src/`. Обычно `src` — это layout, а не пакет.
3. **`tests/conftest.py:43-52`**: список `TABLES` не содержит `scenario_versions` и `round_presets`. Сейчас они всё равно очищаются каскадом от `users`, но зависимость неявная и сломается при изменении FK.
4. **`ui/shared/api_client.py:56`** держит один `httpx.Client` на процесс Streamlit без явного лимита пула. При 500 участниках на одном процессе стоит задать `httpx.Limits`.
5. **Магическое число 32** в кэше preview ([app.py:336](src/aml_workshop_simulator/ui/participant/app.py#L336)) — вынести в константу с комментарием, зачем именно 32.
6. **`api/main.py:137-144`**: обработчик `Exception` не сохраняет ничего о причине. Даже без полноценного логирования стоит хотя бы `traceback` в stderr, иначе 500-я не диагностируется вовсе.
7. **Endpoint `GET /api/v1/admin/game-config/default`** ([admin/rounds.py:78-84](src/aml_workshop_simulator/api/routers/admin/rounds.py#L78-L84)) не упомянут в `docs/api.md` — `grep -n "game-config" docs/*.md` не даёт ни одного совпадения. Админка от него зависит: без него не открывается вкладка «Создать раунд» из базовой конфигурации.

---

## 8. Непроверенные области и причины

| Область | Причина |
| --- | --- |
| Нагрузочное тестирование на 500 участников | Нет ни окружения, ни инструмента; требуется VM, сопоставимая с целевой, и профиль Wi-Fi площадки. `docs/operations.md` §2 требует этого как release gate — **остаётся невыполненным приёмочным условием** |
| Playwright-наборы (`tests/ui/test_playwright_*.py`) | В контейнере ревизии нет пакета `playwright`; кроме того, модули не собираются из-за P2-6. Установка браузера в образ проекта выходит за рамки «не менять настройки» |
| Selenium-наборы | Требуют Chrome/chromedriver в контейнере; корректно помечаются `skipped` |
| E2E (`tests/e2e/test_full_round.py`) | Часть тестов перезапускает контейнер PostgreSQL и делает `pg_dump`/`pg_restore` — нужен docker-in-docker; тесты сами вызывают `pytest.skip` при отсутствии docker |
| TLS, обратный прокси, security headers | В `docker-compose.yml` прокси нет; проверка требует развёртывания по `docs/deployment.md` на VM с DNS и сертификатом |
| Восстановление из резервной копии | Runbook `docs/operations.md` §11 не прогонялся: восстановление в рабочую базу — разрушительная операция, вне полномочий ревизии |
| Долгоживущие сессии, TTL 4 часа, истечение и ротация | Требует управляемого времени; частично покрыто `tests/integration/test_auth_sessions.py` |
| Браузеры кроме Chromium | Использовался только Chromium; Safari/Firefox не проверялись |
| Реальные мобильные устройства | Проверялась эмуляция viewport, а не устройство: реальные touch-таргеты, экранная клавиатура и `100vh` в мобильном Safari не воспроизводятся |
| Светлая тема на всех размерах | Замерена только контрастность; полная матрица размеров снималась в тёмной теме |
| Скоринг на большом объёме | Проверен на 1 сценарии; поведение `score_round` в одной транзакции на 500 сценариях (время, блокировки) не измерялось |
| Модель CatBoost и генератор датасета | `services/catboost_features.py` и `scripts/generate_catboost_sample_data.py` вне HTTP-контура; покрыты `tests/unit/test_file_configuration.py`, отдельно не ревизовались |

---

## 9. План исправлений

### Этап 1 — до любого следующего развёртывания

| № | Задача | Оценка |
| --- | --- | --- |
| 1 | **P0-1**: seed не должен ронять сервис из-за исторического раунда; отделить seed от запуска uvicorn | 0.5–1 день |
| 2 | Тест обновления: раунд ссылается на удалённую карточку → `seed()` завершается успешно | 0.5 дня |
| 3 | Задокументировать в `docs/deployment.md` порядок обновления и способ восстановления | 2 часа |

### Этап 2 — до мастер-класса

| № | Задача | Оценка |
| --- | --- | --- |
| 4 | **P1-1 + P2-4**: keyset-пагинация для списка участников; кнопка «Показать ещё» в админке | 1 день |
| 5 | **P1-2**: решить судьбу `reveal` и привести код и документацию к одному ответу | 0.5 дня |
| 6 | **P1-3**: показывать завершённый раунд участнику без сценария | 2 часа |
| 7 | **P2-1**: заменить несуществующие CSS-переменные админки на рабочие значения | 2 часа |
| 8 | **P2-2**: починить перенос кнопок шага на 1101–1500 px | 2 часа |
| 9 | **P2-6**: перенести `importorskip` выше импорта драйвера в Playwright-наборах | 15 минут |
| 10 | **P2-7**: стабилизировать `step_id` кандидата — минус один тяжёлый запрос на rerun | 1 час |

### Этап 3 — эксплуатационная готовность

| № | Задача | Оценка |
| --- | --- | --- |
| 11 | **P2-5**: структурированное логирование по `docs/operations.md` §7-8 + автоматическая проверка отсутствия PII в логах | 1–2 дня |
| 12 | Нагрузочный тест на 500 участников (release gate из `docs/operations.md`) | 1–2 дня |
| 13 | Зафиксировать зависимости lock-файлом; собирать образ из него | 0.5 дня |
| 14 | Конфигурация `ruff` + минимальный CI (unit + integration + lint) | 0.5 дня |
| 15 | Прогнать runbook восстановления из резервной копии на копии данных | 0.5 дня |

### Этап 4 — качество и чистота

| № | Задача | Оценка |
| --- | --- | --- |
| 16 | **P2-3**: убрать двойной учёт квоты `anonymous` | 1 час |
| 17 | Удалить мёртвый код: `db/repositories/`, `core/enums.py`, `ROUND_TRANSITIONS`, `SENSITIVE_HEADERS` (P3-2, P3-3) | 2 часа |
| 18 | Устранить расхождения документации и реализации: политика блокировки, `cursor` в `docs/api.md`, жизненный цикл раунда (P3-5) | 0.5 дня |
| 19 | Мелкие UX: контраст надзаголовка, целые числа в редакторе, привязка факторов риска к шагу, запуск остановленного раунда (P3-1, P3-4, P3-6, P3-7) | 1 день |
| 20 | `pyproject.toml`, установка пакета, отказ от правки `sys.path` | 0.5 дня |

---

## 10. Артефакты ревизии

| Артефакт | Расположение | В коммит |
| --- | --- | --- |
| Этот отчёт | `PROJECT_AUDIT.md` | **да** |
| Тесты ревизии (10 тестов) | `tests/audit/` | нет — согласно условию «закоммитить только MD-отчёты»; лежат в рабочем дереве |
| Скриншоты, 18 файлов, 9 размеров × 2 приложения | `tests/artifacts/audit-2026-08-30/*.png` | нет — каталог в `.gitignore` |
| Измерения раскладки | `tests/artifacts/audit-2026-08-30/layout-measurements.json` | нет |
| Резервная копия БД до ревизии | `…/scratchpad/aml_simulator_before_audit.dump` | нет |

Тесты ревизии запускаются так же, как остальные наборы:

```bash
python -m pytest tests/audit -q
```

---

## 11. Статус устранения

Раздел добавлен после исправления. Сами замечания выше не редактировались — это
исторический снимок ревизии; здесь только их судьба.

Ветка `fix/audit-remediation`, девять коммитов, каждый называет закрываемые пункты.

| № | Статус | Коммит | Как проверено |
| --- | --- | --- | --- |
| P0-1 | Исправлено | `Keep the seed running…` | Штатная команда старта отработала на восстановленном из дампа сломанном состоянии: `rc=0`, отброшены ровно `international v1` и `crypto_exchange v1`, раунд сохранил `id`/`title`/`status`, получил `card_snapshots` длиной 4; `users=3 scenarios=1 versions=5 results=1 audit=5` без потерь; повторный запуск идемпотентен |
| P1-1 | Исправлено | `Page every growing list…` | Обход курсором отдаёт все 130 участников без повторов; `limit=500` → 200, `limit=501` → 422; попутно устранены два скрытых дефекта того же обработчика (см. ниже) |
| P1-2 | Исправлено | `Make revealing nicknames…` | `?reveal=true`: аноним → **401**, участник → **403**, ведущий → **200**. Маскированный борд остался публичным |
| P1-3 | Исправлено | `Make revealing nicknames…` | Участник без сценария видит завершённый раунд в `/rounds/mine` со `scenario_status: null` и открывает по нему лидерборд |
| P2-1 | Исправлено | `Fix the interface defects…` | Границы таблиц `1px solid` в обеих темах (было `0px none`); три уровня заголовков — три разных цвета |
| P2-2 | Исправлено | `Fix the interface defects…` | Ни одной кнопки с переносом на 11 размерах окна, включая 1101×800 и 1366×768 |
| P2-3 | Исправлено | `Count a step once…` | `limit_usage["anonymous"] == "10000.00"` для карточки с `quota_category="anonymous"`; карточка из двух разных квот по-прежнему учитывается в обеих |
| P2-4 | Исправлено | `Page every growing list…` | Курсор реализован во всех пяти обработчиках; в `docs/api.md` не осталось описанного, но не работающего параметра |
| P2-5 | Исправлено | `Implement the structured logging…` | JSON-строки с обязательными полями §7; поиск по `X-Request-ID` из ответа находит всю цепочку; тест перебирает весь denylist §7 по логу полного раунда |
| P2-6 | Исправлено | `Close the operational gaps…` | `pytest tests --collect-only`: было `Interrupted: 2 errors`, стало **443 собрано** |
| P2-7 | Исправлено | `Fix the interface defects…` | Возврат к уже просчитанному состоянию цепочки стоит **0 запросов** к `/preview` |
| P3-1 | Исправлено | `Fix the interface defects…` | Контраст `.aml-kicker` — **4.88:1** на светлой теме и **9.0:1** на тёмной при пороге AA 4.5:1 |
| P3-2 … P3-13 | Исправлено | этапы 6-8 | См. соответствующие коммиты |
| Гипотеза 1 | **Подтвердилась**, исправлено | `Delete dead code…` | Веса ресурсов квантуются до двух знаков, проверка редактора стала точной и совпадает с серверной |
| Гипотеза 2 | Не проверялась | — | Нагрузочный тест на 500 участников по-прежнему не проводился: нет окружения. Остаётся невыполненным приёмочным условием `docs/operations.md` §2 |
| Гипотеза 3 | Не менялась | — | Порядок статусов в `/rounds/current` оставлен как есть: участник продолжает видеть свою цепочку после остановки раунда. Требует решения ведущего, а не правки кода |
| Улучшения §7.1-§7.7 | Выполнены | этапы 5, 7-9 | `pip install -e .` работает, `ruff check` чист, пул `httpx` ограничен |

### Дефекты, найденные при исправлении и не попавшие в отчёт

1. **`fileConfig` в `migrations/env.py` глушил логирование приложения.** Вызов без
   `disable_existing_loggers=False` отключает каждый уже созданный логгер. Любой
   процесс, который сначала мигрирует, а потом пишет в лог, — а `seed_database
   --migrate` делает ровно это — работал молча. Обнаружено потому, что заглушило
   тесты §5.
2. **Список участников считал все версии черновиков в базе.** `version_counts`
   группировал `scenario_versions` целиком, без фильтра по раунду: тысячи строк на
   один запрос списка из пятисот.
3. **Фильтр `scenario_status` применялся после выборки.** Полная страница могла
   вернуться неполной и прочитаться как последняя.
4. **`/rounds/mine` мог вернуть `limit + 1` строк** — текущий раунд добавлялся
   поверх уже ограниченного списка.
5. **Маскированные ники нумеровались заново на каждой странице** — «Игрок #1»
   дважды читалось бы как дележ первого места.

### Что осталось открытым

* **Нагрузочный тест на 500 участников** (гипотеза 2) — приёмочное условие
  `docs/operations.md` §2, не выполнено.
* **Lock-файл зависимостей** (§5.1). `requirements.txt` по-прежнему использует
  нижние границы; `docs/security.md` §3 требует pinned lock. Не входило в объём.
* **Порядок статусов в `/rounds/current`** (гипотеза 3) — вопрос к ведущему.
* **Собственный access-log uvicorn** дублирует событие `request_completed`. Не
  трогалось: это параметр запуска контейнера, а не код.
