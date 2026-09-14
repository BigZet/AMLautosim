# Реестр падений полного набора

71 failure и 1 setup error. Это исходный прогон с importlib; успешные аудиторские повторы не меняют его статус. Полные трассы остаются локально и не публикуются из-за возможных токенов фикстур.

| Модуль | Проверка | Первичное направление разбора |
|---|---|---|
| tests.api.test_all_operation_parameters | `test_all_parameters_are_exposed_and_saved[salary]` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_all_operation_parameters | `test_all_parameters_are_exposed_and_saved[incoming_transfer]` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_all_operation_parameters | `test_all_parameters_are_exposed_and_saved[card_transfer]` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_all_operation_parameters | `test_removed_parameters_are_rejected_without_saving[salary-context-channel-bank]` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_all_operation_parameters | `test_removed_parameters_are_rejected_without_saving[salary-context-channel-None]` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_all_operation_parameters | `test_removed_parameters_are_rejected_without_saving[salary-context-time_of_day-day]` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_all_operation_parameters | `test_removed_parameters_are_rejected_without_saving[salary-context-velocity-normal]` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_all_operation_parameters | `test_removed_parameters_are_rejected_without_saving[salary-action_details-employer_profile-verified_employer]` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_all_operation_parameters | `test_removed_parameters_are_rejected_without_saving[cash_withdrawal-action_details-cash_purpose-daily_expenses]` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_all_operation_parameters | `test_removed_parameters_are_rejected_without_saving[cash_withdrawal-action_details-withdrawal_location-home_region]` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_all_operation_parameters | `test_removed_parameters_are_rejected_without_saving[cash_withdrawal-context-recipient_type-known_counterparty]` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_all_operation_parameters | `test_removed_parameters_are_rejected_without_saving[card_transfer-action_details-transfer_purpose-family_support]` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_all_operation_parameters | `test_removed_parameters_are_rejected_without_saving[card_transfer-action_details-recipient_relationship-family]` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_all_operation_parameters | `test_removed_parameters_are_rejected_without_saving[incoming_transfer-context-recipient_type-known_counterparty]` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_auth | `test_participant_data_is_private` | Старая chain-фикстура; текущий v8-повтор прошёл (6 тестов). |
| tests.api.test_concurrency | `test_submission_races_autosave` | Старая chain-фикстура; текущий v8-повтор прошёл (6 тестов). |
| tests.api.test_concurrency | `test_submission_races_cutoff` | Старая chain-фикстура; текущий v8-повтор прошёл (6 тестов). |
| tests.api.test_concurrency | `test_state_is_one_nonblocking_snapshot_during_scoring` | Старая chain-фикстура; текущий v8-повтор прошёл (6 тестов). |
| tests.api.test_concurrency | `test_concurrent_submit_retries_record_once` | Старая chain-фикстура; текущий v8-повтор прошёл (6 тестов). |
| tests.api.test_concurrency | `test_concurrent_scorers_publish_once` | Старая chain-фикстура; текущий v8-повтор прошёл (6 тестов). |
| tests.api.test_configuration_validation | `test_invalid_update_keeps_round_and_audit_unchanged[removed_field]` | Тест пытается изменить версию существующего раунда либо ожидает другую ошибку. |
| tests.api.test_configuration_validation | `test_invalid_update_keeps_round_and_audit_unchanged[salary_channel]` | Тест пытается изменить версию существующего раунда либо ожидает другую ошибку. |
| tests.api.test_configuration_validation | `test_invalid_update_keeps_round_and_audit_unchanged[inverted_range]` | Тест пытается изменить версию существующего раунда либо ожидает другую ошибку. |
| tests.api.test_configuration_validation | `test_snapshot_and_seed_reference_reject_invalid_config[removed_field]` | Ссылка теста на удалённый символ seed. |
| tests.api.test_configuration_validation | `test_snapshot_and_seed_reference_reject_invalid_config[salary_channel]` | Ссылка теста на удалённый символ seed. |
| tests.api.test_configuration_validation | `test_snapshot_and_seed_reference_reject_invalid_config[inverted_range]` | Ссылка теста на удалённый символ seed. |
| tests.api.test_contract_versions | `test_snapshot_roundtrip_in_postgresql[7]` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_contract_versions | `test_snapshot_roundtrip_in_postgresql[8]` | Пересмотреть DTO снимка против редактируемого DTO (включая risk_model) и старую схему. |
| tests.api.test_contract_versions | `test_expanded_create_is_blocked_before_writes` | Пересмотреть DTO снимка против редактируемого DTO (включая risk_model) и старую схему. |
| tests.api.test_contract_versions | `test_config_rejection_is_atomic[expanded-409]` | Пересмотреть DTO снимка против редактируемого DTO (включая risk_model) и старую схему. |
| tests.api.test_contract_versions | `test_no_evaluation_or_cutoff_for_injected_expanded_round` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_contract_versions | `test_legacy_golden_scenario_read_and_score` | Тест вызывает модель с неподдерживаемым/незакреплённым снимком. |
| tests.api.test_counterparties | `test_counterparty_autosave_replay_reload_and_catalog_snapshot` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_counterparties | `test_legacy_round_rejects_expanded_fields_without_losing_ids` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_expanded_release | `test_released_round_full_cycle_and_emergency_creation_switch` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_expanded_release | `test_no_in_place_upgrade_and_disabled_default` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_gameplay | `test_incoming_profiles_complete_game[domestic_bank-anonymous_new_account]` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_gameplay | `test_incoming_profiles_complete_game[domestic_bank-anonymous_established_account]` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_gameplay | `test_incoming_profiles_complete_game[domestic_bank-regular_sender]` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_gameplay | `test_incoming_profiles_complete_game[foreign_bank_kg-anonymous_new_account]` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_gameplay | `test_incoming_profiles_complete_game[foreign_bank_kg-anonymous_established_account]` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_gameplay | `test_incoming_profiles_complete_game[foreign_bank_kg-regular_sender]` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_gameplay | `test_incoming_profiles_complete_game[crypto_exchange-anonymous_new_account]` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_gameplay | `test_incoming_profiles_complete_game[crypto_exchange-anonymous_established_account]` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_gameplay | `test_incoming_profiles_complete_game[crypto_exchange-regular_sender]` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_gameplay | `test_incoming_profiles_complete_game[payment_service-anonymous_new_account]` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_gameplay | `test_incoming_profiles_complete_game[payment_service-anonymous_established_account]` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_gameplay | `test_incoming_profiles_complete_game[payment_service-regular_sender]` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_incoming_contract | `test_incoming_card_preview_save_submit_and_score` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_incoming_contract | `test_explicit_seed_reset_replaces_game_but_keeps_accounts_and_sessions` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_nicegui_forms | `test_registration_login_and_full_workshop` | Пересмотреть DTO снимка против редактируемого DTO (включая risk_model) и старую схему. |
| tests.api.test_nicegui_game | `test_editor_conflict_and_submit_without_lost_updates` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_nicegui_game | `test_lost_response_replays_original_command_and_preserves_new_input` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_nicegui_game | `test_poll_started_before_save_cannot_restore_old_steps` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_nicegui_participant_editing | `test_parameters_and_amount_remain_editable_after_autosave` | UI добавляет перевод без обязательного отправителя; сохранение не выполнено. |
| tests.api.test_profile_history | `test_draft_freeze_two_players_reload_and_immutable_after_start` | Тест пытается изменить версию существующего раунда либо ожидает другую ошибку. |
| tests.api.test_purchases | `test_freeze_preview_save_submit_score_and_result` | Timeout подготовки БД; отдельно не воспроизведён, затем обнаружена несовместимая фикстура снимка. |
| tests.api.test_purchases | `test_purchase_hidden_from_legacy_catalog_and_rejected_in_v7` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.api.test_rounds | `test_restart_clears_game_preserves_accounts` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_rounds | `test_unsent_chain_hidden_from_admin_and_deleted_at_cutoff` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_rounds | `test_custom_configuration_controls_submission` | Тест вызывает модель с неподдерживаемым/незакреплённым снимком. |
| tests.api.test_scenarios | `test_direct_submission_and_retry` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_scenarios | `test_invalid_submit_preserves_attempt[False]` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_scenarios | `test_invalid_submit_preserves_attempt[True]` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_scenarios | `test_autosave_revision_and_uuid_conflicts` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_scenarios | `test_preview_and_page_reload` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_scenarios | `test_invalid_cards_and_chains[missing_goal-400]` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_scoring | `test_ranking_ties_access_and_shared_results` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.api.test_scoring | `test_scoring_failure_rolls_back_scores_but_keeps_cutoff` | Сначала исправить обязательные ID сторон в сценарии; целевая проверка не достигнута. |
| tests.load.test_nicegui_workshop | `test_fifty_participants_poll_save_submit_score` | Старая chain-фикстура; нагрузочный повтор с v8 прошёл. |
| tests.unit.test_contract_versions | `test_expanded_typed_roundtrip_and_legacy_unchanged` | Проверить устаревшие ожидания каталога/полей/v7 и приоритет сообщений; не отключать без переноса смысла теста. |
| tests.unit.test_purchases | `test_preview_and_scoring_use_same_totals_and_snapshot` | Тест вызывает модель с неподдерживаемым/незакреплённым снимком. |
