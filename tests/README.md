# Проверки FastAPI + NiceGUI

Python 3.13, `pip install -r requirements-dev.txt`, PostgreSQL 16.
Runtime-зависимости полностью зафиксированы в `requirements.txt`.
На Windows задайте `PYTHONUTF8=1` (PowerShell: `$env:PYTHONUTF8='1'`).
`tzdata` входит в runtime lock, поэтому `Europe/Moscow` доступен и на Windows.

```bash
python -m ruff check src scripts tests migrations
python -m pip check
python -m scripts.validate_config
python -m scripts.check_game_balance
python -m pytest -q tests/unit tests/ml -m runtime
```

Режим `importlib` уже задан в `pytest.ini`, поэтому unit, ML и API можно
объединять: `python -m pytest -q tests/unit tests/ml tests/api`.

Для API и нагрузочных тестов задайте `TEST_ADMIN_DATABASE_URL` пользователя
PostgreSQL с правом CREATEDB, направленный на служебную базу `postgres`.
Пароль со специальными символами в URL должен быть percent-encoded.
Используйте отдельный тестовый PostgreSQL.

```bash
export TEST_ADMIN_DATABASE_URL='postgresql://test:encoded-password@127.0.0.1:55439/postgres'
python -m pytest -q tests/api
python -m pytest -q -s tests/load
```

Каждый запуск создаёт `aml_test_<uuid>`, применяет Alembic, при завершении удаляет
только эту базу. Между API-тестами очищаются таблицы временной базы и выполняется seed.
Рабочий `DATABASE_URL` игнорируется. Не запускайте pytest внутри процесса приложения:
conftest меняет настройки до импорта API. При аварийном завершении временная БД
может остаться; удалять можно только базу, принадлежавшую конкретному запуску.

## Покрытие

- Unit: ресурсы, баланс, параметры операций, UI-клиент, контроллеры и формы NiceGUI,
  настройки подключения и входа, сохранённые признаки, ML-tooling и гонки запросов редактора.
- API: сессии и роли, блокировки, bootstrap, миграция и seed, конфигурация,
  preview/save/submit, ревизии и повторы, атомарность и восстановление скоринга.
- NiceGUI: компоненты через user simulation и контроллеры с реальным API/БД,
  формы, редактирование после autosave, вкладки, конфликты и запоздалые ответы.
- Нагрузка: 50 независимых контроллеров с реальным API и PostgreSQL. Это не
  проверка 50 браузеров или производительности целевого сервера.

API использует ASGI TestClient с lifespan и настоящими сервисами и транзакциями.
Контролируемые ошибки скоринга подменяются точечно; БД не заменяется заглушкой.

## Проверка запущенного стека

```bash
python scripts/check_nicegui_transport.py --url http://127.0.0.1:8080
```

Проверяет страницу, HttpOnly/SameSite cookie и настоящий WebSocket handshake.
В браузере отдельно пройти регистрацию, вход участника и организатора, настройку
и старт, редактирование и reload, отправку, расчёт и рейтинг. Проверять сохранение
входа и данных после перезапуска UI/API. Использовать отдельную игру и БД.

Сборка, первый запуск, повторный seed и восстановление резервной копии входят
в контейнерную проверку. Инструкции: [deployment](../docs/deployment.md) и
[operations](../docs/operations.md). Результаты выпуска фиксируются в `docs/current-release.md`.

## Текущая модель

Пакет `aml-game-organizer-settings-v1` проверяется через `test_model_registry`,
`test_game_classifier_release`, `test_package_publication` и API-тесты.
Численные регрессии сверяют 25 цепочек, признаки, вероятности и SHAP.
Архивные модели и их приёмочные тесты сняты с поддержки. Общие API-сценарии
и проверки worker перенесены на v10. Research-тесты генерируют пилотные входы
во временном каталоге; прежние датасеты в репозитории не нужны.

## Контуры и обязательный CI

`suites.json` содержит явную классификацию существующих модулей. В смешанных
модулях отдельные offline-тесты помечены `research`. Новый тест обязан иметь
назначение в реестре или явный `pytestmark = pytest.mark.runtime` (либо другой
один контур). Collection отклоняет отсутствие классификации и двойные назначения.
Inference, package integrity, сохранённые версии, API и UI остаются runtime,
даже если лежат в `tests/ml`. Обучение и генерация датасетов — research.

`--suite-report=run.json` сохраняет выбранные node IDs, ошибки и exit code.
`runtime-inventory.json` защищает от исчезновения обязательных тестов. При
намеренном удалении/переименовании теста изменение inventory должно объясняться
в том же PR. Добавленные тесты обновляют inventory после успешной collection.

```bash
python -m pytest tests/unit tests/ml -m runtime -q --suite-report=runtime.json
python -m scripts.ci_test_policy runtime runtime.json tests/runtime-inventory.json --group unit
python -m pytest tests/api -q --suite-report=api.json
python -m scripts.ci_test_policy runtime api.json tests/runtime-inventory.json --group api
```

Research запускается в отдельном окружении с `requirements-ml.txt`. В
`research-baseline.json` сохранены конкретные известные ошибки, а не широкие
исключения файлов. Новая ошибка, collection failure, исчезновение или пропуск
ранее падавшего теста отклоняются сравнением. Известный долг виден в артефактах;
успех сравнения не означает, что все research-тесты прошли.

```bash
python -m pytest tests/unit tests/ml -m research -q --suite-report=research.json
python -m scripts.ci_test_policy research research.json tests/research-baseline.json
```

CI запускает `runtime-linux`, `runtime-windows`, `api`, `image` и проверку
research-регрессий. После появления jobs эти имена назначаются required checks
ветки master. Отдельный controller load job запускается вручную через `run_load`;
он не подтверждает ёмкость браузерного мастер-класса.

Контейнерный smoke собирает один образ и проверяет migration/seed, readiness,
HTTP, cookie и настоящий WebSocket на disposable Compose-стенде. Команда:

```bash
docker build -f deploy/Dockerfile -t aml-local:verify .
python -m scripts.ci_smoke --image aml-local:verify
```

Пароли smoke генерируются в памяти, порты назначаются на loopback, ресурсы
уникального Compose-проекта удаляются в конце. Рабочие БД не используются.

Аудит зависимостей использует отдельный `requirements-audit.txt` и проверяет
runtime/ML locks при их изменении и по расписанию. Ошибка сети/инструмента
оставляет job неуспешным; отсутствие JSON-отчёта не считается чистым аудитом.

Lockfiles пересобираются с `uv pip compile --universal --python-version 3.13`:
runtime из `requirements.in`, dev из `requirements-dev.in`, ML из
`requirements-ml.in`, audit из `requirements-audit.in`. Режим `--universal`
сохраняет платформенные зависимости, включая Linux uvloop и Windows colorama.
