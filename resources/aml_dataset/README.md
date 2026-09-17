# Актуальный обучающий набор

Обучение текущего выпуска завершено. Принятый набор: 62 000 цепочек,
`game-attribute-context-v1r2-62000`. Он хранится вне runtime-репозитория:
`E:/AMLautosim-artifacts/aml-probability-v1/game-attribute-context-v1r2-62000`.

Итоговые веса, контекст, порядок признаков и подтверждения приёмки находятся в
`resources/catboost_models/aml-game-attribute-context-v1`. Серверу диск E: не нужен.

Для воспроизводимости сохранены исходные наборы `game-attributes-v1r1-62000`
и `game-attributes-v1-60000` на E:. Старые эксперименты и промежуточные выгрузки
перенесены в `E:/AMLautosim-artifacts/archive/final-cleanup-2026-09-18`.
Оставшиеся здесь исторические фикстуры нужны регрессионным тестам и совместимости
с прежними версиями; они не являются датасетом текущего классификатора.

[Проверки выпуска](../../docs/verification/aml-classifier-v1/README.md).
