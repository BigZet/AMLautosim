# Воспроизведение итоговой модели поведения

Модель подключена к новому выпуску игры: [отчёт CatBoost и SHAP](verification/catboost-shap-integration.md). Ниже сохранены команды офлайн-воспроизведения.

Актуальный пакет — [integration-v2-final](../resources/catboost_models/integration-v2-final/README.md).
[Результаты и границы применения](verification/catboost-behavior-v2.md).
Первая модель и release-v2-1 сохранены как отдельный завершённый эксперимент.

Всё выполняется в отдельном CPU-окружении Python 3.13, CatBoost 1.2.10.
Зависимости зафиксированы в requirements-ml.txt. Каталоги результата должны быть новыми.
Перед созданием каталога обучение собирает версии установленных дистрибутивов
из активного интерпретатора через `importlib.metadata`. `environment.txt` содержит
этот список версий, а `environment.json` — сведения о платформе, интерпретаторе
и ML-пакетах. Это инвентаризация окружения, а не замена lock-файла;
установка `pip` в окружение обучения для неё не требуется.
Seeds и критерии второго эксперимента закреплены в config/ml/behavior-v2-protocol.json;
менять их после просмотра test нельзя.

```bash
docker build -f deploy/Dockerfile.ml -t aml-catboost:v1 .
docker run --rm -v "$PWD:/workspace:ro" \
  -v "$PWD/resources/aml_dataset/behavior-v3:/workspace/resources/aml_dataset/behavior-v3" \
  aml-catboost:v1 python -m scripts.aml_dataset.behavior_training \
  --output resources/aml_dataset/behavior-v3/reproduction

docker run --rm -v "$PWD:/workspace:ro" \
  -v "$PWD/resources/catboost_models:/workspace/resources/catboost_models" \
  aml-catboost:v1 python -m scripts.train_behavior_model \
  --dataset resources/aml_dataset/behavior-v3/release \
  --output resources/catboost_models/reproduction-v2

docker run --rm -v "$PWD:/workspace:ro" \
  -v "$PWD/resources/catboost_models:/workspace/resources/catboost_models" \
  aml-catboost:v1 python -m scripts.evaluate_behavior_model \
  --dataset resources/aml_dataset/behavior-v3/release \
  --model resources/catboost_models/reproduction-v2 \
  --output resources/catboost_models/reproduction-v2/evaluation

docker run --rm -v "$PWD:/workspace:ro" \
  -v "$PWD/resources/catboost_models:/workspace/resources/catboost_models" \
  aml-catboost:v1 python -m scripts.package_behavior_model \
  --dataset resources/aml_dataset/behavior-v3/release \
  --experiment resources/catboost_models/reproduction-v2 \
  --evaluation resources/catboost_models/reproduction-v2/evaluation \
  --output resources/catboost_models/reproduction-integration-v2
```

Офлайн-применение в ML-окружении:

```python
from src.aml_workshop_simulator.services.aml_risk_model import AMLRiskModel
model = AMLRiskModel('resources/catboost_models/integration-v2-final')
score = model.predict(steps, config_snapshot)
```

Адаптер проверяет финансовый контракт, допустимость полной цепочки, версии исходников,
схему и контрольные суммы. Прогноз ограничен 0–100. В текущем приложении
`services/model_scoring.py` загружает этот пакет при старте API и формирует
объяснения SHAP. Идентификаторы модели закрепляются в снимке игры и сохраняются
в результатах. Пакет обязателен: если загрузка или проверка не удалась, API
не запускается. Dockerfile включает пакет модели, но не обучающий датасет.
