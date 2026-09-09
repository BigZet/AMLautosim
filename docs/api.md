# API текущей игры

Префикс `/api/v1`. Аутентификация — `X-Session-ID`; вход и регистрация сохраняют
существующий контракт. Полные схемы генерируются FastAPI в `/api/v1/docs`.

| Метод и путь | Назначение |
| --- | --- |
| `GET /rounds/current/state` | Согласованное состояние экрана участника, требуется игровая сессия |
| `GET /rounds/current` | Единственная текущая игра или `null` |
| `GET /rounds/{id}/cards` | Готовые контракты карточек раунда |
| `GET /rounds/{id}/scenario` | Собственное состояние или `null` |
| `PUT /rounds/{id}/scenario` | Автосохранение только до отправки |
| `POST /rounds/{id}/scenario/preview` | Оценить цепочку до отправки |
| `POST /rounds/{id}/scenario/submit` | Одна окончательная отправка |
| `GET /rounds/{id}/result` | Собственная оценка после скоринга |
| `GET /rounds/{id}/leaderboard` | Имена и оценки после входа участника |
| `GET /admin/game-config/default` | Базовая конфигурация |
| `GET /admin/action-cards` | Каталог для настройки |
| `GET /admin/rounds/current` | Текущая игра для администратора |
| `POST /admin/rounds` | Создать игру, если её ещё нет |
| `GET /admin/rounds/{id}` | Конфигурация и состояние |
| `PUT /admin/rounds/{id}` | Изменить настройки до запуска |
| `POST /admin/rounds/{id}/start` | Начать приём сценариев |
| `POST /admin/rounds/{id}/score` | Закрыть приём и рассчитать результаты |
| `POST /admin/rounds/{id}/restart` | Удалить игровое состояние, создать новую настройку |
| `GET /admin/rounds/{id}/participants` | Аккаунты и статусы отправки |
| `GET /admin/rounds/{id}/participants/{participant_id}` | Аккаунт, отправленный сценарий, оценка |
| `PUT /admin/rounds/{id}/participants/{participant_id}/access` | Управлять блокировкой |
| `GET /admin/rounds/{id}/leaderboard` | Оценки без ручных корректировок |
| `GET /admin/rounds/{id}/audit-events` | Аудит только текущей игры |

Все административные маршруты требуют административную сессию. Неотправленные
сценарии не выдаются администратору. Чужие сценарии недоступны через API участника.

Удалены `/active`, `/mine`, список предыдущих раундов, `/activate`, `/stop`,
`/scoring-plan`, `/stats`, история/восстановление сценариев, шаблоны, ручные оценки.
Это согласованное изменение контракта: совместимость со старым UI не сохраняется.

Ошибка имеет поля `code`, `message`, `details`, `request_id`. Ключевые конфликты:
`round_locked`, `round_not_found`, `scenario_submitted`,
`scenario_revision_conflict`, `mutation_id_reused`, `round_config_revision_conflict`.

Порядок вызовов и обработка ошибок описаны в
[плане обновления Streamlit](streamlit-next-step.md).

При ошибке расчёта: `500 scoring_failed`, приём остаётся закрытым. Статусы игры:
`draft` → `active` → `closed` → `scoring` → `completed`.

## Контракты для UI

В Swagger кнопка **Authorize** принимает `session_id` из `/auth/login`;
схема `SessionId` передаёт его в `X-Session-ID`.

`ScenarioStepIn` содержит `step_id`, `card`, `amount`, `context`, `action_details`.
Поля повторов отсутствуют: каждое выполнение — отдельный шаг с новым UUID.
`ScenarioOut` возвращает сохранённые значения, ревизию, ресурсы и
`can_edit`, `can_submit`, `blockers`. Эти разрешения определяет FastAPI.

Ресурсы описаны `ResourceSnapshotOut`, оценки — `ResultOut`, метаданные
карточек — `ActionCardOut`, конфигурация — `GameConfigIn` / `GameConfigOut`.
Произвольный JSON оставлен только для содержимого событий аудита и доказательств
факторов скоринга; структура игровых ответов описана явно.

Схемы ошибок 400/401/403/404/409/422/429/500 заданы как `ErrorEnvelope`.
Readiness использует собственный контракт `ReadyOut`, в том числе для 503.

## Финальная отправка и чтение состояния

`POST /rounds/{id}/scenario/submit` принимает обязательные `steps`,
`expected_revision` (от 0) и `client_mutation_id` (UUID). Сохранение перед
отправкой не обязательно. Валидация, запись сценария и аудит фиксируются одной
транзакцией. Невалидный запрос не изменяет сохранённую цепочку.

Сетевой повтор отправки использует тот же UUID и содержимое; сервер возвращает
зафиксированный сценарий даже после скоринга. Другой UUID или другое содержимое
после отправки дают `409 scenario_submitted`. Конфликт ревизии до отправки —
`409 scenario_revision_conflict`: перечитать состояние, не перезаписывать его
автоматически. Новое содержимое увеличивает ревизию один раз.

`GET /rounds/current/state` возвращает `round`, `scenario`, `result`,
`can_edit`, `can_submit`, `can_view_leaderboard`. Данные и место получены одним
SQL-запросом без блокировок. Если игры нет, три значения равны null,
разрешения false. В открытой игре без сохранения `can_edit=true`,
`can_submit=false`; право отправки текущей локальной цепочки сообщает preview.
Существующие отдельные GET сохранены и используют те же проекции.

Лидерборд участника требует игровую сессию и всегда содержит имена;
`reveal`, `masked`, `revealed` удалены. До завершения расчёта он пуст.
Административный рейтинг остаётся отдельным защищённым маршрутом.

Административный `/close` удалён. `/score` закрывает приём отдельной транзакцией
и запускает расчёт. При ошибке состояние `closed`, доступен повтор `/score`.
