# Повторная проверка и исправления — 16 сентября 2026

**Результат:** закрыты AUD-01–05 исходного аудита и дополнительный AUD-06.
Windows: **537 passed, 1 skipped**; Linux: **538 passed**. Полная сверка
**4413 прогнозов и SHAP под `python -O` прошла**, максимальное отклонение прогнозов — 0.0.

Исправления относятся к текущему рабочему дереву, включая ранее существовавшие
изменения, и к находкам [исходного аудита](../project-audit-2026-09-16/README.md).
При повторном просмотре подтверждён и исправлен ещё один дефект валидаторов — AUD-06.

## Изменения

| Пункт | Исправление | Регрессия |
|---|---|---|
| AUD-01 | `GameEditor.poll` получает state/cards в локальные переменные, повторно проверяет номера poll/write и применяет готовый снимок без `await` | [Тесты гонок](../../../tests/unit/test_game_poll_races.py), [red/green](ui-regression.log) |
| AUD-02 | Длительность сессии, число попыток и длительность блокировки должны быть положительными целыми числами; неверная конфигурация отклоняется при старте | [Настройки](../../../tests/unit/test_runtime_settings.py), [login/lockout/session](../../../tests/api/test_auth.py), [22 passed](auth.log) |
| AUD-03 | Оба trainer используют общий сборщик `importlib.metadata` активного процесса, сохраняют executable/prefix и версии ML-пакетов; проверяют metadata до создания output-каталога | [Тесты](../../../tests/unit/test_training_environment.py), [29 passed](ml-provenance-regression.log) |
| AUD-04 | README, архитектура, инструкции модели, эксплуатации и тестов согласованы с обязательным runtime CatBoost/SHAP | Проверены вызовы при старте API, Dockerfile и сервис скоринга |
| AUD-05 | Обязательные пороги ML-верификатора реализованы явными исключениями; неполные наборы, дубли ID, NaN/Infinity отклоняются, существующий отчёт не перезаписывается | [Тесты](../../../tests/unit/test_verify_model_integration.py), [35 passed](verifier-regression.log) |
| AUD-06 | Проверки review-датасета и его экспорта сохраняются при `python -O`: 39 `assert` заменены явными условными исключениями с прежним типом ошибки | [Тесты](../../../tests/unit/test_aml_dataset_v2.py), [red/green](dataset-validator-regression.log) |

Для AUD-01 дополнительно проверены ошибка получения карточек, сохранность
несохранённого черновика и pending-команды, локальные изменения во время загрузки.
До исправления четыре новых регрессии воспроизводили неверное поведение.

Для AUD-03 проверены оба entry point обучения без вызова `fit`: отсутствующий
или посторонний Python в PATH, uv-окружение без pip, сортировка и нормализация
инвентаризации, отсутствующие или противоречивые metadata. `environment.txt`
содержит установленные версии, а не воспроизводимый lock-файл.

Для AUD-05 проверки полноты, точности прогнозов, аддитивности SHAP и времени
работают в обычном режиме, `python -O` и `PYTHONOPTIMIZE=1`. До исправления
32 негативных теста не получали требуемого отказа; после исправления все
35 целевых тестов прошли. Запись отчёта использует эксклюзивное создание файла.

AUD-06 подтверждён отдельными optimized-процессами: раньше валидаторы принимали
подменённые метки и признаки в package, неверный package hash и метку в CSV.
После исправления все четыре повреждения отклоняются; корректный экспорт принимается.
Рубрика, признаки и содержимое исторических датасетов не менялись.

## Область повторной проверки

| Проверка | Результат | Доказательство |
|---|---|---|
| Windows unit + ML | 401 passed, 1 skipped; 107.41 с | [Лог](unit-ml.log), [JUnit](unit-ml.xml) |
| Windows API + load | 136 passed; 319.21 с | [Лог](api-load.log), [JUnit](api-load.xml) |
| Linux unit + ML | 402 passed; 165.51 с | [Лог](docker-unit-ml.log) |
| Linux API + load | 136 passed; 229.25 с | [Лог](docker-api-load.log) |
| Ruff | Успех | [Лог](ruff.log) |
| Конфигурация и баланс | Успех | [Конфигурация](config.log), [базовый](balance.log), [расширенный баланс](expanded-balance.log) |
| Compose | Сборка и healthy API/UI/PostgreSQL | [Первый запуск](docker-build-start.log), [итоговая сборка](docker-final-build.log) |
| Игровая приёмка и восстановление | Успех, 84 SHAP-фактора, сохранены сессии и результаты | [JSON](docker-acceptance.json) |
| Полная модельная верификация, `python -O` | 4413 строк; отличие прогнозов 0.0; максимальный остаток SHAP 2.27e-13; 482.82 с | [JSON](model-integration.json), [лог](model-integration.log) |

Всего: **Windows — 537 passed, 1 skipped; Linux — 538 passed**.
Пропуск Windows относится к созданию symlink без требуемых системных прав;
соответствующий Linux-тест прошёл. Два предупреждения зависимостей TestClient
(httpx и BlockingPortal) были и до исправлений; они не являются падениями тестов.
`uv pip check` подтвердил совместимость всех 82 пакетов; зависимости не менялись.
Время измерено при параллельных проверках и не является production benchmark.
Первые 100 объяснений заняли 10.43 с при пороге 60 с; p95 одного объяснения — 0.137 с.

Для поиска и проверки связей использованы Serena и Semble. Через `docker_l337`
проверен Docker Engine и запущены Linux unit/ML-тесты. Compose с отдельным env-файлом
запускался через CLI: используемый MCP Compose API не предоставляет параметр env-file.
Отдельный [read-only review](review.md) изменений не выявил блокирующих замечаний.

Контейнерная приёмка использует проект `aml-audit-fixes-20260916` и собственные
тома, API/UI/PostgreSQL на loopback-портах 58400/58480/58439. Полный игровой путь,
повторные submit/score, перезапуск и dump/restore подтверждены
[отчётом](docker-acceptance.json) и [журналом](docker-acceptance.log).
NiceGUI cookie и WebSocket handshake проверены [отдельно](docker-transport.log).
API/load-тесты создают и удаляют собственные БД `aml_test_<uuid>`.
После итоговой сборки API сообщил `ready`, UI — `ok`: [health](final-health.json).
Временные контейнеры, сеть и тома проверки удалены: [очистка](docker-cleanup.log).
Обычные локальные API/UI/PostgreSQL не перезапускались.

Контрольные суммы изменённых исходников и тестов сохранены
[отдельно](checked-source-sha256.json); после прогонов они повторно сверены.
Предсуществовавшие изменения рабочего дерева сохранены. Коммит не создавался.

## Повторение проверок

Из корня проекта, в подготовленном Python 3.13 окружении:

```powershell
$env:PYTHONUTF8 = '1'
.venv/Scripts/python.exe -m ruff check src scripts tests migrations
.venv/Scripts/python.exe -m pytest -q tests/unit tests/ml
# TEST_ADMIN_DATABASE_URL — PostgreSQL с правом CREATEDB, служебная БД postgres.
.venv/Scripts/python.exe -m pytest -q -s tests/api tests/load
.venv/Scripts/python.exe -O -m scripts.verify_model_integration --dataset resources/aml_dataset/behavior-v3/release --predictions resources/catboost_models/experiment-v2/evaluation/predictions.csv --output .local-run/model-integration-fixes-repeat.json
```

Для верификатора output должен быть новым. Конфигурация и баланс проверяются
командами `scripts.validate_config`, `scripts.check_game_balance`
и `scripts.check_expanded_balance` через `python -m`.

## Границы результата

Модель не переобучалась, датасет не генерировался заново; файлы модели и исходники,
закреплённые её контрольными суммами, сохранены. Повторная проверка не заменяет
внешний pentest, production HTTPS, длительную нагрузку и многобраузерную приёмку.
Автоматизация CI остаётся рекомендацией исходного отчёта, а не выполненным изменением.

Исходный отчёт и его пробы оставлены как исторические доказательства: часть проб
специально утверждает старое ошибочное поведение. Для проверки исправлений следует
запускать регрессии из `tests`, перечисленные выше.
