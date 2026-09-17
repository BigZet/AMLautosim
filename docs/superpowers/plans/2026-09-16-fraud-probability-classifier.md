> Актуальный статус на 17.09.2026: игровой датасет из 60 504 цепочек и проверочная
> модель прошли приёмку; серая зона 15,53%. Классификатор внедрён в API/UI v10.
> Все 6060 test-прогнозов совпали точно. Проверены 25 опубликованных примеров
> и браузерный сценарий агента. Работают демонстрация и отдельная активная игра.
> [Выпуск и плейтест](../../verification/aml-classifier-v1/classifier-release-2026-09-17.md).
> Дальнейшая проверка интереса игры реальными людьми остаётся за пользователем.
# Вероятность учебного AML-сценария: Implementation Plan

> **Последний критерий пользователя: 10–20% серой зоны**, `0.1 ≤ p < 0.9`,
> по строкам отложенной игровой выборки. Пакет с 0% теперь не принят.
> Добавлены проверка нижней и верхней границы и запрет загрузки пакетов со
> старыми критериями. Следующий шаг — переработка разметки пограничных сочетаний;
> растягивание вероятностей и случайное изменение меток не допускаются.

> **Новое решение пользователя 17.09.2026 — заменяет прежнюю целевую метку:**
> классификатор оценивает соответствие наблюдаемой цепочки учебным AML-паттернам,
> а не фактический уголовный исход. 100 означает уверенность в классе паттерна.
> [Новый контракт](../../research/2026-09-17-observable-pattern-target.md).
> Корпус `pattern-v1-30000` пересобран; отдельная модель обучена и откалибрована.
> На фиксированном test совпадение с программной разметкой 100%, серая зона 0%.
> Это усвоение учебных правил, не независимое распознавание реального отмывания.
> [Данные, ограничения и результаты](../../../resources/aml_dataset/aml-fixed-history-v1/pattern-v1-30000/README.md).
> Остались самостоятельное дробление вне обучающего покрытия и интеграция нового
> `score_kind` в API/UI. Прежние пункты об уголовной метке ниже исторические.

> **Пересборка по цепочкам 17.09.2026:** новый `chain-v2-30000` содержит 30 000
> строк шести семейств. Парные классы имеют одинаковые суммы, стороны и каналы;
> меняются порядок и интервалы. AUC только по атрибутам сторон = 0,50,
> без этих атрибутов = 0,815. Серая зона около 90%: уверенный скоринг не готов.
> [Новые основания разметки](../../research/2026-09-17-chain-first-labeling.md),
> [корпус и результаты](../../../resources/aml_dataset/aml-fixed-history-v1/chain-v2-30000/README.md).
> Следующий блок относится к предыдущему кандидату и сохранён как история проверки.

> **Проверка 17.09.2026:** кандидат общей истории собран (30 000 строк), но
> предметная приёмка не пройдена. Диагностика выявила зависимость качества от
> заданных генератором частот контрагентов; серая зона полной модели — 54,1%.
> Итоговое обучение, калибровка и выпуск остаются незавершёнными.
> [Разбор и актуальный протокол](../../verification/aml-classifier-v1/fixed-history-label-review-2026-09-17.md).

> **Уточнение пользователя 17.09.2026 — имеет приоритет над прежними пунктами:**
> Во всей игре используется одна неизменная общая предыстория транзакций и один
> существующий профиль. Между участниками и раундами история не меняется.
> Дополнительные профили не вводятся. Варьируются только допустимые цепочки
> операций на общем игровом контексте. Старый отбор по пяти профилям и генерация
> разнообразных предысторий отменены для итогового обучающего корпуса.
> Артефакты `population-draft/v1` и `demo-frozen/v2` сохраняются как исторические
> эксперименты, но не подтверждают выполнение уточнённого требования.
> Требования к группировке, разбиению и контрольным примерам нужно пересогласовать
> с фиксированным общим контекстом; общий фон нельзя выдавать за независимые истории.
> Текущая базовая история — `config/expanded_behavior.json`; её нельзя подменять
> досье из генератора. Обучение по прежнему корпусу не запускать.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить регрессию учебной рубрики на проверенную вероятность AML-класса 0/1, отображаемую на шкале 0–100, с разнообразными допустимыми цепочками и обоснованными низкими/высокими оценками.

**Architecture:** Версионированный контекст v10 расширяет подготовленную семантику v9; отдельный extractor v5 получает только наблюдаемые факты. CatBoostClassifier и числовой калибратор упаковываются вместе с определением исхода, популяцией, схемой и порогами. Старые v8-пакеты и результаты обслуживаются прежним адаптером; новый скоринг выбирается по закреплённому пакету.

**Tech Stack:** Python 3.13, CatBoost 1.2.10, NumPy/pandas, scikit-learn только для offline, FastAPI/Pydantic, PostgreSQL 16, NiceGUI, Docker. Версии перепроверить и закрепить в provenance; runtime калибратора не требует sklearn/pickle.

**Spec:** [AML-поведение, законный контекст и вероятностный классификатор](../../research/2026-09-16-aml-behavior-and-legitimate-context.md). Читать вместе с этим планом.

Обновлено 16.09.2026 после углублённого исследования. Это **план будущей реализации**, не отчёт о выполненных задачах. Историческое имя файла fraud-probability-classifier сохранено для совместимости ссылок; новые API, каталоги и модули используют AML, а не fraud. Исследование и обновление документов не запускают обучение и не переключают действующую игру.

## Глобальные ограничения

- Цель — установленный в учебном сценарии эпизод перемещения/сокрытия преступных доходов. Не подменять его мошенничеством, подозрением, высоким оборотом или нарушением правил.
- `aml_probability = P(y=1 | наблюдения, учебная популяция)`; `risk_score = 100*p`. Равномерность шкалы и точные 0/100 не являются критериями.
- Старые `integration-v2-final`, датасеты, исходники с закреплёнными checksum и сохранённые результаты не перезаписывать.
- Старый v8 остаётся доступен. Подготовленный v9 не выпускать автоматически и его pending-согласование рубрики не отмечать approved. Новый протокол классификации заменяет эту рубрику только для нового v10-пакета.
- v10 сохраняет суммы, комиссии, энергию, время, лимиты карточек и цель текущих expanded defaults. Расширяет только наблюдаемый контекст и семантику его обработки.
- В основном датасете оба класса проходят один и тот же движок и достигают 400 000 ₽ при максимуме 14 действий. Невыполнимый сюжет не исправлять ослаблением одного dataset-validator.
- Скидки за зарплату, покупку и ожидание не участвуют в создании новых меток. Пауза и бытовой фон не гарантируют снижение вероятности.
- Искусственная популяция v1: 50% класса 1 среди confirmed, одинаковое число вариантов на независимую группу. Никаких заявлений о реальной банковской распространённости.
- Неподдержанные контракты/категории и повреждённые пакеты приводят к явному отказу; правила или старый регрессор не служат тихим fallback.
- Обязательные проверки через явные исключения, работающие при `python -O`. Чужие незакоммиченные изменения не включать в коммит автоматически.
- Запуск новой модели разрешается только после полного прохождения заранее зафиксированных gates. Не снижать требования после просмотра test.

## Решения, изменённые исследованием

| Прежний план | Новый контракт |
| --- | --- |
| Неопределённый fraud-класс | AML-класс с отдельной авторской истиной, наблюдениями и статусом review |
| Начать с разметки текущих признаков | Сначала проверить достижимость и добавить связанный контекст |
| Не учтён подготовленный v9 | Использовать его семантику; новый номер игрового контракта v10, extractor v5 |
| Минимум 300 групп | Минимум 1 200 групп происхождения и отдельные gates статистической поддержки |
| Подбирать категории по calibration-check | Фиксированные 0.1/0.9, как в пользовательском запросе; качество на этих границах проверяется |
| Глобальные благоприятные признаки | Факты с областью действия, лимитом суммы и временем доступности |
| 25 участников одного неопределённого контекста | 25 участников в пяти сопоставимых демонстрационных раундах; рейтинги между разными контекстами не смешиваются |

## Контракт данных и публичного результата

### Исход и область наблюдения

Единица — полная цепочка участника плюс неизменяемый контекст раунда, доступный к концу цепочки. `aml_label=1` означает, что в авторском сюжете присутствует хотя бы один AML-эпизод; `0` — законный сюжет без такого эпизода. Наличие законного эпизода не отменяет положительный исход независимого другого эпизода.

~~~json
{
  "scenario_id": "case-001",
  "provenance_group_id": "origin-001",
  "family_id": "shared-expense",
  "aml_label": 0,
  "label_status": "confirmed",
  "review_status": "reviewed",
  "label_source": "authored-case-and-review",
  "label_protocol_version": "aml-labels-v1",
  "label_rationale": "Законный учебный сюжет, проверенный по протоколу",
  "population_id": "aml-game-balanced-v1",
  "split": "train"
}
~~~

Для unresolved: `aml_label=null`, `label_status=unresolved`; исключать из supervised fit, но не из отдельного отчёта по неоднозначности. До review использовать `review_status=authored_unreviewed`. Эти статусы не являются судебными выводами.

Авторская истина и обоснование хранятся отдельно от публичного snapshot. Запрещены в X: метка, статус review, исход/текст расследования, rationale, family/group/scenario ID, split, имена сторон, старый risk score. Скрытый исход не подставлять в evidence.

### Контекст v10

Новые файлы: `schemas/aml_context.py`, `services/aml_context.py`, `services/aml_dataset_features_v5.py` внутри `src/aml_workshop_simulator`. Не переиспользовать имя v4: оно уже занято.

`behavior.aml_context` содержит:
- `version=aml-context-v1`, `as_of`, структурированный `expected_activity` с периодом применимости, типами деятельности и ожидаемыми объёмами в этом периоде;
- `opening_balance_facts`, `purpose_catalog`, `facts`;
- `history_coverage`: `complete|partial|unknown`, границы известного окна;
- facts с полями `id`, `fact_type`, `verification_status`, `provenance`, `available_at`, `valid_from`, `valid_to`, `counterparty_ids`, `operation_codes`, `purpose_code`, `max_credit_amount`, `max_debit_amount`.
- `fact_type`: `source_of_funds|payment_purpose|relationship|opening_balance`. `verification_status`: `verified|unverified|contradicted|unknown`. `provenance`: `scenario_record|customer_statement|independent_record`; это тип учебного свидетельства, не имя реальной организации.
- `purpose_code`: `salary|service_payment|family_support|shared_expense|asset_sale|refund|loan|personal_spending|unknown`. Собственные счета, корпоративные расчётные продукты, торговые документы и блокчейн-граф не добавлять в v1.

`expected_activity` содержит `period_start`, `period_end`, `activity_kinds`, `expected_credit_min`, `expected_credit_max`, `expected_debit_min`, `expected_debit_max`; activity_kinds используют purpose_code выше, суммы — Decimal-строки или null. Неполный диапазон (только один предел) запрещён, min≤max. Это описание ожидаемой активности, а не обязательный лимит: выход за диапазон остаётся наблюдением. `opening_balance_facts` — ссылки на facts типа opening_balance; `purpose_catalog` — список разрешённых purpose_code с пользовательскими подписями. IDs/подписи в X не включать.

В шаге: `purpose_code` и опциональный `claim_id`; они выбирают доступное объяснение, но не меняют facts. Сервер отклоняет попытку передать/изменить status, provenance или новый произвольный fact. Неизвестный claim ID — ошибка валидации; известное объяснение, не соответствующее операции, остаётся наблюдаемым несовпадением и не получает покрытие.

Для каждого факта отдельно учитывать остаток разрешённого объёма входящих и исходящих. Применять покрытие хронологически, не более суммы шага и оставшейся суммы основания, только при совпадении роли, операции и периода. Факт, появившийся после cutoff, не используется. Это сопоставление объяснения и операции, не финансовая трассировка.

Все игроки одного раунда получают один и тот же публичный контекст; snapshot замораживается при запуске. Между раундами профили могут различаться. Проверенные факты встречаются в обоих классах; их наличие не является меткой законности.

### Выход и совместимость

Объяснение v4: `schema_version=4`, `score_kind=aml_probability`, `aml_probability`, `raw_margin`, `uncalibrated_probability`, `explanation_space=raw_margin`, `context_status=complete|partial`, `model_identity`, SHAP-факторы и отдельное описание калибратора. `context_status` вычисляется по наличию ожидаемых полей/покрытию истории; не по p и не объявляется confidence.

`risk_score` сохраняется для совместимости. Вероятность хранится без округления; в UI один десятичный знак, на краях <0,1% и >99,9%, без «AML исключён». Категории: low при p<0.1; review при 0.1≤p<0.9; high при p≥0.9. Вычислять категорию до округления.

Старое объяснение v3 остаётся отдельной веткой discriminated union; старый регрессионный риск не показывать как вероятность. Конкретные значения context и его hash закреплены в раунде; package contract signature описывает семантику и финансовые ограничения, а не один конкретный профиль.

## Task 1. Протокол меток, каталог и достижимость

**Files:** создать `docs/ml/aml-labeling-v1.md`, `config/ml/aml-classifier-v1-protocol.json`, `scripts/aml_dataset/aml_labels.py`, `scripts/check_aml_casebook.py`, `tests/unit/test_aml_label_contract.py`, `resources/aml_dataset/aml-v1/pilot/casebook.jsonl`.

**Interfaces:** `validate_label(record: dict) -> None`; `audit_casebook(casebook: Path, protocol: Path) -> dict`. Неверные метки/статусы дают ValueError. Достижимость проверяется тем же ресурсным движком, что игра; не через старый риск.

- [x] Зафиксировать 10 семейств P01–P10 исследования, факторы F01–F25 и ограничения F26–F32. Пилот: 120 полных кейсов — по 40 confirmed legitimate, confirmed AML и unresolved; по четыре каждого статуса на семейство.
- [x] Каждому кейсу задать истину, отдельно публичные наблюдения, источник гипотезы, причину метки, необходимые facts и запретные сведения. Первичную допустимость финансов проверять до создания UI.
- [x] Для каждого confirmed проверить альтернативное законное/подозрительное объяснение. Если доступных наблюдений недостаточно, оставить кейс для измерения неразличимости; не выдавать произвольный исход за уверенно наблюдаемый.
- [x] Провести отдельный от автора проход предметного review и сохранить reviewer/method/date/rationale. Автоматизированную проверку не называть человеческой экспертизой. До завершения этого review статус не reviewed и выпуск закрыт.
- [x] Тест → ожидаемое падение → реализация валидатора → повторный целевой прогон:

~~~python
import pytest
from scripts.aml_dataset.aml_labels import validate_label

def test_unresolved_cannot_be_negative():
    with pytest.raises(ValueError, match="unresolved"):
        validate_label({"aml_label": 0, "label_status": "unresolved"})
~~~

**Run:** `.venv/Scripts/python.exe -m pytest -q tests/unit/test_aml_label_contract.py`.

**Acceptance:** 120 записей с прозрачной provenance; структурный/ресурсный аудит без ошибок, причины неразличимости перечислены. Если необходимый законный сюжет неосуществим, массовая генерация не начинается; отчёт содержит конкретное ограничение, а не замену кейса удобной меткой.

## Task 2. Контекст v10 и наблюдаемые признаки

**Files:** создать три модуля контекста/extractor выше и `tests/unit/test_aml_context.py`, `tests/unit/test_aml_features.py`; изменить `schemas/round_config.py`, `domain/contract_versions.py`, `services/round_configuration.py`, серверную обработку шагов и `ui/nicegui/game.py`. Новые описания признаков: `config/model/aml-classifier-v1-feature-descriptions.json`.

**Interfaces:** `validate_context(context: dict, config: dict) -> None`; `resolve_evidence(steps: list, config: dict) -> list[dict]` возвращает по шагу покрытую сумму входящих/исходящих, applicable/contradicted/unknown и IDs объясняющих facts; `extract_features(steps: list, config: dict) -> dict` возвращает только allowlist `aml-observable-v5.0`.

- [x] Реализовать контракт v10 поверх семантики v9; создание новых v10-раундов пока закрыто release-gate. Ресурсная проекция допускается только для расчёта ресурсов, никогда для скоринга старой моделью.
- [x] Добавить публичное чтение facts/expected_activity и выбор purpose/claim; сервер остаётся единственным источником статуса проверки. Истина кейса и reviewer metadata не доступны через игровые API.
- [x] Сопоставлять факты по правилам раздела «Контекст v10»; проверять Decimal-суммы ≥0, timezone-aware даты, уникальные ID, ссылки на существующие стороны и операции, from≤to, доступность на момент решения.
- [x] Добавить признаки объяснённой суммы, противоречий, неизвестности, соответствия цели/профиля, концентрации по эпизодам и полноты истории. Не копировать финальные AML-выводы в признаки. RU/KG и ID исключить из X.
- [x] Явно различать нулевой знаменатель, отсутствие информации и нулевое наблюдаемое значение. Для сравнения с историей требовать сопоставимый период/тип; месячный доход не сравнивать напрямую с искусственным оборотом раунда.
- [x] Зафиксировать тесты подмены fact, повторного расходования основания, будущего свидетельства, переименования ID, известной пустой/неизвестной истории и v8/v9-совместимости; затем реализовать и проверить.

~~~python
from src.aml_workshop_simulator.services.aml_context import resolve_evidence

def test_evidence_cannot_cover_more_than_its_amount(aml_context_fixture):
    config, steps = aml_context_fixture(
        fact_limit="50000.00", debit_amounts=["30000.00", "30000.00"]
    )
    rows = resolve_evidence(steps, config)
    assert [row["covered_debit_amount"] for row in rows] == ["30000.00", "20000.00"]
~~~

Фикстура создаёт два хронологических дебета с одним применимым verified-фактом; её создать в том же test-модуле. Отдельно проверить, что лимиты credit и debit независимы и не удваиваются внутри одного направления.

**Run:** `.venv/Scripts/python.exe -m pytest -q tests/unit/test_aml_context.py tests/unit/test_aml_features.py tests/unit/test_semantic_v9.py`.

**Acceptance:** одинаковый X offline/runtime; нейтральное переименование не меняет X; прежние resource outcomes сохранены. Все 120 кейсов после материализации v10 проходят полный игровой валидатор.

## Task 3. Датасет и независимость проверки

**Files:** создать `scripts/aml_dataset/aml_training.py`, `scripts/build_aml_dataset.py`, `scripts/validate_aml_dataset.py`, `tests/unit/test_aml_dataset.py`; новый каталог `resources/aml_dataset/aml-v1/release`.

**Interfaces:** `build_dataset(casebook: Path, protocol: Path, output: Path) -> None`; `audit_dataset(directory: Path) -> dict`. CLI: `--casebook --protocol --output` у build; `--dataset --output` у validate; существующий output не перезаписывать.

- [ ] Зафиксировать seed 2026091601, population manifest, версии генератора и точный feature allowlist. Начальный объём — 30 000 confirmed-строк, ≥1 200 групп происхождения; строки вариаций не считаются независимыми кейсами.
- [ ] Одному origin давать одинаковое число вариантов; для 1 200 групп — 25 на группу. Если групп больше, одинаковое целое число вариантов и не менее 30 000 строк. Не создавать фиктивную независимость простым новым UUID.
- [ ] Строить provenance-граф по родителям, общим историям, near-duplicate структурам и контрфактическим парам; его связная компонента — единица split. Общая версия шаблона фиксируется отдельно как family, а не скрывается новым group_id.
- [ ] Разделить группы 60/15/10/5/10%: train/validation/calibration-fit/calibration-check/test. Оба класса в каждом; баланс групп и строк 50/50 с допуском одной целой группы. Стратификацию и округление записать в manifest.
- [ ] Все профили и каналы включают оба класса; запрещено генерировать только AML для crypto или только legitimate для verified. Невозможные клетки coverage явно помечать, а не заполнять ложными метками.
- [ ] Отдельные challenge-наборы: masked-context/unresolved; новые комбинации факторов; заранее выбранные family-held-out сюжеты. На них не подбирать модель и не смешивать их с основным test.
- [ ] Проверять игровой движок, уникальность IDs, дубли X между split, утечки provenance, конечность признаков, соответствие JSONL/CSV и все checksum. Наблюдаемо одинаковые конфликтующие метки сохранять внутри одной группы и учитывать как ограничение.

~~~python
import pytest
from scripts.aml_dataset.aml_training import audit_dataset

def test_related_variants_must_not_cross_splits(aml_dataset_fixture):
    directory = aml_dataset_fixture(
        shared_origin=True, splits=["train", "test"]
    )
    with pytest.raises(ValueError, match="group"):
        audit_dataset(directory)
~~~

Фикстура пишет минимальный валидный датасет с общим origin и двумя вариантами; создать в test-модуле.

**Run:** `.venv/Scripts/python.exe -m pytest -q tests/unit/test_aml_dataset.py`; затем `python -m scripts.validate_aml_dataset --dataset resources/aml_dataset/aml-v1/release --output .local-run/aml-dataset-audit.json`.

**Acceptance:** manifest/counts/group report, coverage и отчёт о коллизиях проверены. Меньший датасет допускается только как pilot со статусом not-release-ready. Старые открытые test используются исключительно как development/legacy compatibility.

## Task 4. Базовые модели и классификатор

**Files:** создать `scripts/aml_classifier.py`, `scripts/train_aml_classifier.py`, `tests/ml/test_aml_classifier.py`; использовать `scripts/training_environment.py`. sklearn закрепить только в ML-зависимостях.

**Interface:** `train(dataset: Path, protocol: Path, output: Path) -> None`; CLI `--dataset --protocol --output`. Выход: CBM, feature schema, class mapping, train/validation predictions, candidate table, environment/source checksums.

- [ ] Сравнить constant-prior, логистическую регрессию и CatBoostClassifier. Препроцессинг обучать только на train; регрессор оставить лишь отдельной диагностикой ранжирования.
- [ ] CatBoost: Logloss, CPU thread_count=4, seed=2026091601, iterations=3000, learning_rate=0.04, early_stopping_rounds=150; depth=[4,6,8], l2_leaf_reg=[3,10]. Без class weights и oversampling.
- [ ] Основной кандидат — минимум validation LogLoss; при разнице ≤0.002 выбрать меньшую depth, затем меньше деревьев, затем l2=10. Дополнительные seeds 2026091602/2026091603 — проверка устойчивости выбранных гиперпараметров, не подбор по test.
- [ ] Для стабильности требовать разброс validation AUC ≤0.03 и каждой доли уверенных ошибок ≤0.03 между seeds. Иначе эксперимент не ready, отчёт объясняет нестабильность.
- [ ] Сверять положительный класс через classes_, запретить недостающие/лишние/переставленные входные колонки без явного приведения по schema; не обучать модель на calibration/test.

~~~python
positive_index = list(model.classes_).index(1)
p_raw = model.predict_proba(pool)[:, positive_index]
~~~

**Tests:** переставленный class mapping; отсутствие 1; нарушение schema; save/load probability residual ≤1e-8; отказ перезаписи output; отсутствие обращения к test в train CLI.

**Run:** `.venv/Scripts/python.exe -m pytest -q tests/ml/test_aml_classifier.py`.

**Acceptance:** воспроизводимый выбранный кандидат и baseline comparisons; test остаётся закрыт.

## Task 5. Калибровка и количественная приёмка

**Files:** создать `scripts/calibrate_aml_classifier.py`, `scripts/evaluate_aml_classifier.py`, `services/aml_calibration.py` внутри package, `tests/ml/test_aml_calibration.py`.

**Interfaces:** `fit_calibrator(raw_margin, labels, method) -> dict`; `apply_calibrator(raw_margin, artifact: dict) -> ndarray`; `evaluate(dataset: Path, package: Path, split: str) -> dict`. CLI calibration: `--dataset --model --protocol --output`; evaluation: `--dataset --package --split --output`.

- [ ] На calibration-fit обучить sigmoid(a*margin+b), a>0, и isotonic. No-calibration означает sigmoid исходного margin, а не возврат margin как p.
- [ ] Isotonic допускать при ≥1 000 различных наблюдаемых кейсов и ≥100 provenance-групп в calibration-fit; иначе исключить до выбора. Это консервативный проектный gate, не универсальная теорема.
- [ ] Хранить sigmoid a/b или isotonic x/y knots и правило линейной интерполяции с ограничением на крайние значения. Валидировать конечность, отсортированность x, монотонность y и диапазон [0,1]; без pickle.
- [ ] Выбрать по calibration-check LogLoss; improvement <0.002 считать ничьей и предпочесть no-calibration, затем sigmoid, затем isotonic; при improvement≥0.002 требовать Brier не хуже baseline более чем на 0.001. Пороговые категории остаются 0.1/0.9.
- [ ] Проверить calibration-check: оба класса, ≥20 provenance-групп в каждой крайней категории. Недостаточная поддержка — not-release-ready, не основание сдвинуть пороги после просмотра test.
- [ ] Один раз открыть основной test для выбранного пакета. Все численные критерии ниже — заранее заданные проектные gates, не результаты исследования.

| Gate на основном confirmed-test | Требование |
| --- | --- |
| ROC-AUC | ≥0.90 |
| Average Precision | > фактической доли класса 1 |
| LogLoss и Brier | Оба лучше constant-prior из train |
| ECE | ≤0.05, 10 фиксированных равных интервалов; также reliability table и размеры bins |
| Серая зона | mean(0.1≤p<0.9) ≤0.20 |
| Ложная высокая уверенность | P(p≥0.9\|y=0) ≤0.05 |
| Ложная низкая уверенность | P(p<0.1\|y=1) ≤0.05; p=0.1 относится к серой зоне |
| Precision high / NPV low | Каждый ≥0.90, крайние категории непусты |
| Поддержка | ≥60 происхождений с каждым классом на test; ≥30 групп в каждом крайнем диапазоне |
| Неопределённость метрик | 2 000 group-bootstrap повторов, seed 2026091601, 95% percentile CI; верхняя граница двух уверенных ошибок ≤0.10, нижняя precision/NPV ≥0.85 |
| Подгруппы | Профиль и канал: ≥100 строк и ≥20 групп каждого класса для заявления о качестве; при меньшей поддержке — insufficient-support |

- [ ] Публиковать строковые и равновзвешенные по группам метрики. Релизные критерии выше проверять для обеих агрегаций; большое семейство не должно скрывать провал малого.
- [ ] Для групповой агрегации вес каждой строки равен 1/n_group, где n_group — число строк её provenance-группы; нормировать веса при вычислении среднего. Для условных метрик использовать соответствующее подмножество и перенормировку. В bootstrap переносить все строки выбранных групп вместе.
- [ ] Для обязательных поддержанных профилей/каналов требовать уверенные ошибки ≤0.10; при недостаточной поддержке не заявлять пакет универсальным и не включать такой профиль в release allowlist. Во всех bins с <30 группами явно отмечать недостаточность данных.
- [ ] Публиковать confusion matrix, ROC/PR, reliability, histogram по истинному классу, абляции context/features, collisions и coverage challenges. Grey-zone gate не применять к unresolved; не исключать сложные confirmed после получения p.
- [ ] Sensitivity к иной доле класса — отдельный анализ предположений, без автоматической prior-коррекции действующей игры.
- [ ] Для bootstrap с вырожденной выборкой метрику помечать undefined; если валидных повторов <95%, CI-gate не пройден. Считать целые группы, не случайные строки.
- [ ] Не принимать нулевую ширину bootstrap-CI при отсутствии ошибок за доказательство нулевого риска. Дополнительно считать одностороннюю 95% Clopper–Pearson границу по событию «в группе есть хотя бы одна уверенная ошибка»: верхняя граница ≤0.10 отдельно среди групп с y=0 и y=1. Для групп, попавших в high/low, верхняя граница события «есть неверное предсказание в этом диапазоне» ≤0.15. Использовать scipy.stats.beta.ppf с явными крайними случаями k=0/n; это консервативная групповая проверка, её не подписывать как строковую precision.

~~~python
import numpy as np
import pytest
from src.aml_workshop_simulator.services.aml_calibration import apply_calibrator

def test_sigmoid_origin():
    artifact = {"method": "sigmoid", "a": 1.0, "b": 0.0}
    assert apply_calibrator(np.array([0.0]), artifact)[0] == pytest.approx(0.5)
~~~

**Tests:** p=0.1/0.9, NaN/Inf, extreme margins, отрицательный a, пустые/несортированные knots, round-trip, совпадение offline/runtime interpolation, пустые категории и недостаточные группы.

**Run:** `.venv/Scripts/python.exe -m pytest -q tests/ml/test_aml_calibration.py`.

**Acceptance:** все gates пройдены одновременно. Провал остаётся в отчёте. После изменения модели по результату test этот набор становится development; новая независимая приёмка требует нового test.

## Task 6. Пакет и корректное объяснение

**Files:** создать `scripts/package_aml_classifier.py`, `src/aml_workshop_simulator/services/aml_probability_model.py`, `tests/ml/test_aml_probability_model.py`; пакет `resources/catboost_models/aml-classifier-v1`.

**Interface:** `AMLProbabilityModel(package: Path).predict(steps: list, config: dict) -> dict` возвращает raw margin, raw/calibrated p, context_status, model_identity и SHAP decomposition.

- [ ] Manifest: task=binary_classification, positive_class=1, score_kind=aml_probability, population/protocol versions, extractor v5, v10 contract semantics, financial rules signature, allowed profiles/categories, thresholds, evaluation status.
- [ ] SHA-256 охватывает CBM, calibration, feature schema, dictionary, protocol, thresholds, evaluation summary и исходники нового адаптера/экстрактора. Не переназначать checksum старого пакета.
- [ ] Контрактный hash не привязывать к одному профилю: проверять версию и финансовые правила, допустимые категории и schema. Полный hash конкретного context закреплять отдельно в round snapshot.
- [ ] На реальной бинарной модели подтвердить: base_margin + sum(contributions) = RawFormulaVal с residual≤1e-6; sigmoid(raw_margin) совпадает с исходной вероятностью положительного класса.
- [ ] Основное SHAP-объяснение хранить в raw_margin. Для sigmoid допустим отдельный calibrated logit a*margin+b; для isotonic только отдельное преобразование суммарного margin. Не складывать «процентные вклады».
- [ ] Проверить повреждённые файлы, неверный class mapping, неизвестный feature/profile, отсутствие калибратора, несовместимый config и finite outputs. Smoke: сохранение/загрузка меняет p не более чем на 1e-8.

**Run:** `.venv/Scripts/python.exe -m pytest -q tests/ml/test_aml_probability_model.py tests/ml/test_model_scoring.py`.

**Acceptance:** пакет самодостаточен без sklearn; старый пакет проходит прежнюю совместимость; release-ready зависит от метрик и provenance, не от наличия model.cbm.

## Task 7. API, хранение, UI и рейтинг

**Files:** изменить `services/model_scoring.py`, `services/scoring_service.py`, `schemas/scoring.py`, `schemas/leaderboard.py`, `ui/nicegui/shap_result.py`; проверить consumers через Serena/Semble. Тесты `tests/api/test_aml_integration.py`, `tests/unit/test_aml_result_ui.py`. Документация `docs/api.md`, `docs/architecture.md`, `docs/operations.md`.

**Interface:** discriminated union v3/v4 из раздела «Выход»; adapter registry выбирает пару contract_version/score_kind и точный pinned package identity.

- [ ] Ввести explicit dispatch v8-regressor/v10-classifier. Для v9 scoring остаётся закрыт. Новый раунд закрепляет package/calibrator/schema/threshold/context hashes до начала.
- [ ] Хранить p, explanation v4 и identity атомарно в существующем JSON результата; существующий Decimal risk_score — производное округлённое 100*p. Подтвердить возможности JSON column; новая Alembic-ревизия только если действительно требуется, старую 0001 не править.
- [ ] GET завершённого результата не вызывает модель и не пересчитывает прошлые результаты. Retry, restart и потерянный HTTP-ответ не создают повторный scoring.
- [ ] Показывать «Вероятность AML-сценария в учебной модели», исходную категорию, missing-context status и конкретные факторы. SHAP обозначать как связь признаков с прогнозом, не доказательство и не причинный эффект.
- [ ] Новый рейтинг сохраняет ресурсную часть; игровая скрытность=100*(1-p), отдельная leaderboard version. Разные контексты/раунды имеют отдельные рейтинги.
- [ ] Сначала тесты старого v3 и нового v4, p=0.09999/0.1/0.89999/0.9, запрета фальсификации контекста и round-trip вероятности, затем реализация.

~~~python
def test_probability_category_uses_unrounded_value(aml_result_renderer):
    output = aml_result_renderer(probability=0.09999)
    assert output["category"] == "low"
    assert output["score_kind"] == "aml_probability"
~~~

Фикстура вызывает тот же view-model результата, который использует NiceGUI; создать в test-модуле. Дополнительно сохранить реальные API-ответы v3/v4 как fixtures и проверить discriminated parsing.

**Run:** `.venv/Scripts/python.exe -m pytest -q tests/unit/test_aml_result_ui.py tests/api/test_aml_integration.py` с отдельной тестовой PostgreSQL.

**Acceptance:** исторические результаты читаются со старой семантикой, новые с новой; доступ организатора/игрока соблюдён, labels/rationale отсутствуют в публичных snapshots.

## Task 8. Сквозная проверка и демонстрация после внедрения

**Files:** создать `scripts/verify_aml_integration.py`, `scripts/create_aml_demo.py`, `tests/unit/test_verify_aml_integration.py`, `docs/verification/aml-classifier-v1/README.md`; обновить deploy/package docs после успешной проверки.

**Interfaces:** verifier CLI `--dataset --package --output`; demo CLI `--dataset --package --casebook --output`, пять повторений `--api-url` и пять соответствующих `--ui-url` в порядке frozen casebook. `--casebook` указывает на каталог freeze. Пять изолированных экземпляров приложения нужны потому, что каждый хранит один текущий раунд. Credentials получает из `AML_DEMO_ADMIN_EMAIL` / `AML_DEMO_ADMIN_PASSWORD`, не из git и не из командной строки; выводит приватный файл доступа в `.local-run`.

- [x] До оценки заморозить 20 полных контрольных кейсов: 10 AML с ожидаемым p≥0.9, 10 legitimate с p<0.1; плюс пять ambiguous. У каждого есть заранее записанное основание и expected band, полный контекст и SHA-256. Текущая версия: `resources/aml_dataset/aml-v1/demo-frozen/v2`, после отдельного AI-review точных 25 записей; вероятности ещё не измерялись. Независимость повторно проверяется перед fit относительно полного окончательного корпуса.
- [ ] Создать пять demo-раундов на одинаковых финансовых правилах с разными публичными профилями; по два AML, два legitimate и одному ambiguous участнику в каждом. Не смешивать их рейтинги; дать индекс со ссылками на все раунды.
- [ ] Независимый состав demo не использовать для train/calibration/tuning. Эскизы P01–P10 уже открыты и являются development-материалом; финальные конкретные контрольные реализации должны быть новыми группами и заморожены до оценки.
- [ ] Verifier сверяет offline/runtime на полном списке test IDs из manifest: p≤1e-8 residual, SHAP≤1e-6, class mapping, thresholds, context/model hashes. Старое число 4413 не переносить.
- [ ] Проверить negative paths при обычном Python, -O и PYTHONOPTIMIZE=1. При gate failure не создавать успешный отчёт; существующий output не перезаписывать.
- [ ] Проверить lint, unit/ML, API/load на Windows/Linux, контейнерный запуск, restart, backup/restore, scoring retry, отсутствие/повреждение пакета. Производительность: 100 последовательных объяснений ≤60 с на описанном стенде; публиковать p95 и время 50 участников.
- [ ] В браузере проверить профиль/facts, заполнение цепочки, отправку, результат, SHAP, рейтинг и вход организатора. Сохранить доказательства, версию образа и точные команды воспроизведения.
- [ ] Отчёт demo показывает все 25 цепочек, суммы, интервалы, стороны, историю, основания, ожидаемый и фактический диапазон, ошибки. Для 20 однозначных все диапазоны обязательны; ambiguous не обязаны получить строго 0.5 и не входят в gate 10+10.
- [ ] При несовпадении не заменять контрольный кейс удачным. После дообучения на его основе он становится development; нужна новая независимая приёмка.
- [ ] Включать v10 только для новых раундов после всех gates. Хранить старый образ/пакет для старых игр. Для rollback закрыть создание новых v10; уже начатые v10 требуют своего pinned-пакета, не переключаются на v8.

**Команды после реализации** — новые CLI будут созданы задачами выше:

~~~powershell
$env:PYTHONUTF8 = '1'
.venv/Scripts/python.exe -m ruff check src scripts tests migrations
.venv/Scripts/python.exe -m pytest -q tests/unit tests/ml
# TEST_ADMIN_DATABASE_URL указывает на отдельную PostgreSQL с CREATEDB.
.venv/Scripts/python.exe -m pytest -q -s tests/api tests/load
.venv/Scripts/python.exe -O -m scripts.verify_aml_integration --dataset resources/aml_dataset/aml-v1/release --package resources/catboost_models/aml-classifier-v1 --output .local-run/aml-verification-optimized.json
$env:PYTHONOPTIMIZE = '1'
.venv/Scripts/python.exe -m scripts.verify_aml_integration --dataset resources/aml_dataset/aml-v1/release --package resources/catboost_models/aml-classifier-v1 --output .local-run/aml-verification-env-optimized.json
Remove-Item Env:PYTHONOPTIMIZE
~~~

**Acceptance:** полный verification report, все 20 однозначных demo прошли диапазоны, пять ambiguous опубликованы, рабочие ссылки и приватные креды организатора переданы пользователю. Демонстрация не заменяет оценку на полном test.

## Порядок выполнения и условия остановки выпуска

1 → 2 → 3 → 4 → 5 → 6 → 7 → 8. Для каждой кодовой задачи: отрицательный тест, ожидаемый отказ, минимальная реализация, целевой зелёный прогон, review diff. Отдельные review/commit возможны по задачам; не включать чужой worktree автоматически.

Этапы 1–3 доказывают предметную состоятельность и достижимость; 4–5 — качество вероятностей; 6–8 — интеграцию. Нельзя пропустить контекст, оставить старую рубрику или объявить пилот готовым релизом ради скорейшего predict_proba.

Если нет различимости, необходимого числа групп, полноценного review или одновременного прохождения gates, итог — documented not-release-ready. Протокол следующего эксперимента получает новую версию; тестовые данные, повлиявшие на решения, больше не независимы. Исследование не обещает, что желаемая доля серой зоны достижима при любом наборе наблюдений.

## Проверка покрытия исследования

| Требование исследования | Реализация |
| --- | --- |
| Определение AML и неизвестного исхода | Task 1, контракт данных |
| 32 фактора с границей наблюдаемости | Task 1 coverage; F26–F32 вне релиза |
| Законные основания и отсутствие глобальных скидок | Task 2, пары P01–P10 |
| v8/v9 compatibility и новый контекст | Tasks 2, 6, 7 |
| Групповые split, коллизии, synthetic population | Task 3 |
| Проверенная вероятность и небольшая серая зона | Tasks 4–5, совместные gates |
| Корректный SHAP | Task 6 |
| Старые результаты, безопасность API, рейтинг | Task 7 |
| Десять высоких / десять низких после внедрения | Task 8 |
| Реальные источники и пределы выводов | Связанный research MD, реестр R1–R12/M1–M5 |

Технические основания: [CatBoost predict_proba](https://catboost.ai/docs/en/concepts/python-reference_catboostclassifier_predict_proba), [SHAP](https://catboost.ai/docs/en/concepts/shap-values), [калибровка scikit-learn](https://scikit-learn.org/stable/modules/calibration.html). Численные критерии и интерфейсы выше — проектные решения AMLautosim, а не требования этих источников.

