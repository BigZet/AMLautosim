# Проверки FastAPI + NiceGUI

Python 3.13, `pip install -r requirements-dev.txt`, PostgreSQL 16.
Runtime-зависимости полностью зафиксированы в `requirements.txt`.

```bash
python -m ruff check src scripts tests migrations
python -m pip check
python -m scripts.validate_config
python -m scripts.check_game_balance
python -m pytest -q tests/unit
```

При объединении unit и API в одном запуске используйте
`python -m pytest -q --import-mode=importlib tests/unit tests/api`:
в каталогах есть одноимённые модули тестов. Обычный режим импорта pytest
выдаёт `import file mismatch`; это не основание исключать тесты.

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
  настройки подключения, сохранённые признаки и генератор отложенного CatBoost.
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
[operations](../docs/operations.md). Результаты фиксируются в `docs/verification/`.

## Офлайн CatBoost

Тесты `tests/ml` выполняются отдельно в образе `deploy/Dockerfile.ml` с
`requirements-ml.txt`. Они не требуют БД. Команды и отдельная интеграционная
проверка оценки без вызова fit: [обучение CatBoost](../docs/catboost-training.md).

## Интеграция CatBoost и SHAP

Для нового выпуска: `tests/ml/test_model_scoring.py`, `tests/api/test_model_integration.py`, `tests/unit/test_expanded_result_ui.py`. Нужны CatBoost 1.2.10 и отдельная PostgreSQL. Проверка всех 4413 прогнозов и SHAP — `python -m scripts.verify_model_integration`; параметры приведены в [отчёте](../docs/verification/catboost-shap-integration.md). Старые v7 API-сценарии описывают снятый с эксплуатации пилот и не подтверждают новый контракт.
