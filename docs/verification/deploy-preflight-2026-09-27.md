# Проверка перед деплоем, 2026-09-27

Проверено локальное рабочее дерево поверх `b00a096a9ac54b764bc737aeb53df87e82e1b0e8`,
включая незакоммиченные исправления UI и автосохранения. Это кандидат, не опубликованный
релиз. Production, его БД, балансировщик и DNS не изменялись.

## Исправления UI

При смене источника входящего перевода несовместимое назначение заменяется допустимым
значением по умолчанию до preview/save. Стабильный снимок значений карточки предотвращает
пересоздание полей после серверной канонизации сохранения. Позиция меню обновляется
после монтирования popup, чтобы список не оставался `visibility:collapse`.

Интерактивная проверка до исправления: 8 операций, 176 комбинаций основных атрибутов
и отдельные проверки ожиданий. После исправления: 43 изменения без повторной попытки
открытия списка, desktop и ширина 390 px, без ошибок JavaScript. Узлы полей сохраняются
при обычных правках. Это проверка ширины браузера, не физического телефона.
Материалы: `.local-run/ui-attributes-20260927/`.

## Проверки кандидата

| Проверка | Результат |
| --- | --- |
| Runtime/unit/ML | 669 passed, 1 skipped (право Windows на symlink), inventory сохранён |
| Ruff общий и runtime-профиль | passed |
| mypy, настроенная область проекта | passed (4 source files) |
| Зависимости локальной `.venv` | `uv pip check`: все 102 пакета совместимы |
| Research | 349 passed, 69 известных failures; baseline policy passed, новых failures нет |
| API | Linux PostgreSQL 16: все 223 passed; первоначально Windows PostgreSQL с locale C: 222 passed, 1 failed (кириллический поиск) |
| Chrome / Firefox / WebKit | 63 сценария passed: Firefox + WebKit 42, системный Chrome 21 |
| Linux Docker image | сборка passed, Python 3.13.15 |
| Container smoke | migrations/head, model, readiness, restore copy, повторный seed без изменения аккаунтов, cookie, WebSocket, ingress source restriction — passed |
| Production Compose | отдельный проект, подсеть 172.30.29.0/24, именованные тома, release → запуск API/UI/worker/ingress, readiness и внешний 403 — passed |
| Compose interpolation | default/custom subnet, trusted CIDR, отсутствие опубликованных API/UI/DB-портов, project-scoped volumes — passed |
| Runtime packaging после правки | 3 passed, 1 skipped; две сборки архива дали одинаковый SHA-256 |

Начальная локальная попытка runtime-тестов без `PYTHONUTF8=1` остановилась на чтении
UTF-8 fixture в Windows. Повторный полный прогон с настройкой из CI успешен.
Первая сборка получила неподдерживаемую диагностическую метку `GIT_SHA`; пересобрана
с разрешённым `development`, после чего контейнерные проверки прошли.
В native Windows PostgreSQL 16.15 подтверждены `datctype=C`, `datcollate=C`:
`lower('Ёлка')` остаётся `Ёлка`. Linux PostgreSQL 16 с `en_US.utf8` возвращает
`ёлка`; все 223 API-теста повторно прошли на нём. Схема и поиск приложения не менялись.
В первом browser-прогоне отсутствовал `chromium_headless_shell-1243`: 21 ошибка
setup возникла до открытия приложения. Медленная загрузка браузера остановлена;
повтор прошёл с `--browser chromium --browser-channel chrome`. Этот прогон
не следует выдавать за проверку pinned Chromium или Safari на реальном iPhone.

Локальные машинные отчёты и логи: `.local-run/deploy-preflight-*`.
Секреты disposable-стендов находятся в приватном local state и не входят в поставку.

## Поставка и откат

План: [deploy-rollback.md](../deploy-rollback.md). Production Compose допускает
отдельную подсеть через `AML_NETWORK_PREFIX`, адреса и trusted CIDR меняются вместе.
Инструкция запуска включает scoring-worker. Архив теперь содержит production Compose,
пример env, nginx-конфигурацию и план отката.

Архив `.local-run/aml-deployment-20260927.tar.gz`, 367 файлов:
`f85e18922e90cb0d73aeb36f13c4577a58212aad49ec50b0661eec70f7db1b2d` (SHA-256).
Секреты, локальные БД и browser state исключены allowlist-упаковщиком.
Локальный образ `aml-preflight:20260927` имеет `GIT_SHA=development`; он проверяет
рабочее дерево, но не заменяет registry digest выпуска из конкретного commit.

## Перед реальным переключением

- Зафиксировать все изменения, получить успешный CI выбранного SHA и registry digest
  через release workflow. Не выдавать текущий HEAD за идентификатор незакоммиченного кода.
- Инвентаризировать установленный production и сохранить его реальные образы,
  конфигурацию, storage, БД и off-host backup. Проверить восстановление именно старого
  окружения и записать команды переключения/возврата LB.
- Green использует отдельную пустую БД; blue сохраняет прежние данные. Миграция старых
  аккаунтов/игр в green не проверена. Откат возвращает состояние blue на границе
  переключения; записи green сохраняются отдельно, автоматического merge нет.
- Проверить TLS, source IP LB, HTTP redirect и WebSocket на сервере.
- PERF-01 остаётся открытым: целевой p95 для 60 участников и двухчасовой soak не
  подтверждены. Результаты предыдущих замеров находятся в `perf-2026-09-26-after/`.
  Локальный функциональный прогон не закрывает этот вопрос ёмкости.

69 research failures остаются известным baseline исследовательского контура,
а не успешными тестами. Веса модели не менялись.
