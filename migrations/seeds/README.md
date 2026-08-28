# Database seeds

Идемпотентные начальные данные:

- `action_cards.py` — версии карточек и parameter schema;
- `bootstrap_admin.py` — создание первого администратора из environment secret;
- `demo_round.py` — только dev/test раунд без PII.

Повторный запуск seed не должен создавать дубликаты.
