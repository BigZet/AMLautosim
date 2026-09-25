# Образ приложения

[Dockerfile](Dockerfile) собирает общий образ для двух ролей: FastAPI и NiceGUI.
Команды, зависимости запуска и healthcheck заданы в [Compose](../docker-compose.yml).

Python 3.13; зависимости фиксированы в `requirements.txt`. Готовые бинарные колёса загружаются
в отдельной стадии; в runtime нет компиляторов. Код принадлежит root и доступен
только для чтения, процессы работают от `app` (UID 10001).
NiceGUI пишет состояние в том `/home/app/nicegui`, режим каталога 0700.

В образ входят код, конфигурация, миграции и служебные скрипты.
Тесты, документация, локальные данные, секреты и отложенные CatBoost-адаптер
и генератор исключены. Подробности: [развёртывание](../docs/deployment.md).

## Выпуск по commit

Workflow `Release image` запускается вручную для выбранного ref. Он делает checkout
точного SHA, один раз собирает образ на закреплённом Python 3.13.15 image digest,
проверяет его с PostgreSQL 16 и публикует тот же образ с commit tag в GHCR.
Артефакт `release-provenance` содержит digest и OCI revision/source. Проверять SHA
артефакта против выбранного commit; не создавать исправления поверх старого образа.
`/health/live` сообщает безопасный `git_sha`; секреты и пути в health не возвращаются.

Production использует `compose.production.yml` и отдельный защищённый env-файл
по образцу `.env.production.example`. `AML_IMAGE` должен содержать `@sha256:`
из проверенного выпуска. Host config не монтируется поверх образа. UI/API/БД не публикуют порты. Отдельный nginx ingress на 8080 принимает только
проверенный source IP балансировщика и локальные health probes. TLS завершается
на внешнем балансировщике; прямой доступ должен возвращать 403.
До обновления сохранить предыдущий **registry digest** и совместимую резервную копию.
На обследованном старом сервере registry digest не установлен: известны только
локальные image IDs, см. production-inventory.json. Их нельзя выдавать за digest.

Порядок команд (из корня checkout, env-файл вне репозитория):

```sh
docker compose --env-file /secure/aml.env -f deploy/compose.production.yml pull
docker compose --env-file /secure/aml.env -f deploy/compose.production.yml up -d db
docker compose --env-file /secure/aml.env -f deploy/compose.production.yml run --rm release
docker compose --env-file /secure/aml.env -f deploy/compose.production.yml up -d --no-deps --wait api ui ingress
```

`release` — единственный одноразовый процесс миграции и seed, без демонстрационного
раунда. API workers не мигрируют схему. Для чистой установки нужен bootstrap пароль;
повторный seed сохраняет существующие аккаунты и игру. Smoke проверяет установку,
pg_dump/pg_restore в отдельную БД и повторную release-команду с сохранением аккаунтов.
Это проверка disposable-стенда, не восстановление production backup.

Откат: остановить новые API/UI, вернуть предыдущий проверенный `AML_IMAGE`, затем
запустить API/UI без downgrade только если старая версия совместима с новой схемой.
При несовместимой схеме восстановить backup в новую БД, проверить миграции/readiness
и целостность игры, переключить подключение. Не выполнять слепой Alembic downgrade.

## Пути и настройки

`AML_PROBABILITY_MODEL_PATH` выбирает текущую модель v10. В образе находится
только `aml-game-organizer-settings-v1`. Readiness проверяет текущую и закреплённую
модель игры; liveness не читает БД и модели. UISettings проверяет URL, порт,
cookie и каталог хранения. В production `/home/app/nicegui` — приватный том.
