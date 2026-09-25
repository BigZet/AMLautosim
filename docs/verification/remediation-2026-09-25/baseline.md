# Baseline исправлений — 25 сентября 2026

База: `5fc9dcc69f3b8a1f7ce2fed5f2aac20fa90be012`, подтверждённый удалённый master.
Реализация: `codex/review-remediation-2026-09-25`, отдельный worktree Codex.
Исходные рабочие каталоги и production не изменялись.

## Окружение и воспроизведение

- Windows, CPython 3.13.15, зависимости из `requirements-dev.txt`; контрольные суммы lockfiles и пакетов — в `inventory.json`.
- Docker Desktop 29.8.0 запущен; PostgreSQL 16 в отдельном контейнере, опубликован только на loopback на динамическом порту. Порт 55432 оказался запрещён Windows; существующие контейнеры/БД не использовались.
- LFS-объекты моделей и исследовательских данных восстановлены из локального кэша.
- Исходная установка не содержит Windows timezone database. После фиксации ошибки установлен `tzdata==2026.4`; закрепление зависимости входит в T02. `python` в командах ниже означает Python этого virtualenv.
- Без `-X utf8` collection падает на `tests/unit/test_contract_versions.py` с `UnicodeDecodeError` (cp1252). Для дальнейших проверок используется явный UTF-8; CI также должен задавать `PYTHONUTF8=1`.

| Проверка | Exit | Результат |
|---|---:|---|
| `python -m pytest tests/unit -q` | 2 | 1 collection error: кодировка JSON |
| `python -X utf8 -m pytest tests/unit -q` | 1 | 348 failed, 477 passed, 1 skipped, 79 errors; timezone database отсутствовала при старте |
| `python -X utf8 -m pytest tests/api -q` | 1 | 1 passed, 164 errors; timezone database отсутствовала |
| Runtime/package/bootstrap/contract subset после установки tzdata | 1 | 8 failed, 20 passed, 1 skipped, 5 errors; текущий package отклонён из-за source EOL |
| `python -X utf8 -m pytest tests/ml -q` после установки tzdata | 1 | 36 failed, 77 passed; это расположение файлов, а не утверждённая классификация research |
| `python -m ruff check src scripts tests migrations` | 0 | 0 ошибок с существующим набором правил |

Полные команды, exit codes и node IDs сохранены в `baseline-results.json`. Логи и JUnit — локальные артефакты `.superpowers/sdd/2026-09-25-review-remediation/`; итоговый CI загружает новые JUnit отдельно. Исходные числа не являются результатом исправленной версии. Классификация runtime/research выполняется по назначению теста в T02.

## Модели и EOL

Текущий пакет — `aml-game-organizer-settings-v1`; полная identity записана в `inventory.json`.
Package SHA-256: `6b9c93935933e806ca733d22f36bdb99ef9660a4f6946e4f7d27b2fb748c5fbe`.
Сохранить v8 `integration-v2-final` и закреплённые v10 `aml-game-v1`, `aml-game-relaxed-v1`, `aml-game-attributes-v1`, `aml-game-attribute-context-v1`. Остальные пакеты не удаляются без инвентаризации потребителей T14.

Для диагностического replay создана временная копия исходников из git-объектов базы. У каждого файла выбран вариант EOL, **побайтово совпадающий с историческим SHA-256**, затем штатный verifier проверил весь пакет. Восемь compatibility sources соответствуют CRLF, `aml_context.py` и четыре inference sources — LF. Это только восстановление исторического окружения для эталона, не эвристика runtime.

На 25 сохранённых цепочках записаны полные вероятности, входные признаки окон и SHAP. Исходная полная identity совпадает с read-only проверкой production. Контрольный набор используется T01 и последующими перевыпусками; менять эталон ради прохождения тестов нельзя.

## Production: read-only наблюдение

Доступ по SSH подтверждён. Санитизированная инвентаризация — `production-inventory.json`; окружение с секретами и данные пользователей не выгружались.

- API: `aml-runtime:20260920`, image ID `a9a792b0dc963a3b744e3edb8fb976030e476b2b862ad144a4f3807d05dc56b7`.
- UI: `aml-runtime:20260920-amount-format`, image ID `fa24a140d55d64f3beaf6e6f8fe1f771b45d467c4708bae5b7eb6eef95bb28a2`.
- OCI revision отсутствует у обоих образов: равенство исходников production коммиту базы не доказано.
- UI опубликован на `0.0.0.0:8080` и `[::]:8080`; API/БД — на loopback. Наличие публикации ещё не доказывает доступность через внешний firewall.
- Compose монтирует host config поверх `/app/config`; это входит в исправления воспроизводимости.
- Правила облачного firewall, фактические source IP балансировщика и off-host backup пока не проверены. Изменение работающего сервера не входит в этот PR.

## Решения и ограничения

T13 выполняется полностью по решению пользователя: PostgreSQL jobs, recoverable worker, прогресс. Недоступные проверки реальных устройств и production останутся явно обозначенными; они не заменяются эмуляцией. Поддержка 60/300 участников не заявляется до соответствующих измерений.
