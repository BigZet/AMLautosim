# End-to-end tests

Проверки полного Docker Compose deployment:

- `test_full_round.py` — регистрация, сбор сценария, submit, scoring и leaderboard;
- `test_admin_workflow.py` — настройка раунда, block и adjustment;
- `test_restart_recovery.py` — восстановление server-side draft после перезапуска UI;
- `test_security_surface.py` — публичны только HTTPS-маршруты UI.

Данные только синтетические и без PII.
