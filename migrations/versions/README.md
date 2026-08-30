# Alembic versions

Текущая цепочка ревизий:

| Revision | Что добавляет |
| --- | --- |
| `2988b0ed1f98_initial_schema` | Базовые таблицы: users, sessions, action_cards, rounds, scenarios, scoring_results, leaderboard_adjustments, audit_events |
| `b1c4d7e93a20_constraints_and_indexes` | Проверочные ограничения, частичные и составные индексы |
| `c73f5a1e9d04_draft_history_lifecycle_presets_sessions` | История черновиков, полный жизненный цикл раунда, пресеты настроек, технические данные входа |
| `e84a6d2c190f_remove_trust_and_rename_available_steps` | Удаление игрового ресурса «Доверие» и переход со слотов на доступные шаги |

`c73f5a1e9d04` подробно:

- новая таблица `scenario_versions` (append-only история сохранений) с уникальным
  `(scenario_id, revision)` и backfill: каждый существующий сценарий получает версию 1
  из своих текущих `steps`;
- `scenarios.current_version_id` и `scenarios.submitted_version_id` с FK на неё;
- новая таблица `round_presets` и `rounds.preset_id`;
- `rounds.stopped_at`, `rounds.restarted_from_round_id`, обновлённый `ck_rounds_status`
  со статусом `stopped`;
- `sessions.ip_address` (`INET` на PostgreSQL), `sessions.user_agent`,
  `sessions.accept_language`, индекс `ix_sessions_user_created`;
- `users.first_login_at` с backfill из `last_login_at`.

Уже примененную миграцию не редактируют: изменение оформляется новой revision.

`e84a6d2c190f` переводит конфигурации раундов и пресетов на схему 4,
правила `game-rules-v3` и формулу `leaderboard-v2`. Остальные ограничения,
параметры операций и факторы риска сохраняются. Веса оставшихся ресурсов
нормализуются пропорционально до суммы 1 с точностью 0.01.

Миграция очищает также сохранённые снимки и старые нарушения по удалённому
ресурсу, пересчитывает флаг допустимости и обновляет хеш конфигурации.
Опубликованные баллы и журнал аудита не пересчитываются: это исторические
записи с исходной версией формулы.

Перед обновлением сделайте резервную копию БД. Удалённые значения восстановить
расчётом нельзя, поэтому обратная миграция запрещена; откат выполняется
восстановлением резервной копии вместе с предыдущей версией приложения.
