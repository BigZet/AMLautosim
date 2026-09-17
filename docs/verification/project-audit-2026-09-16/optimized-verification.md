# Проверка assert в integration verifier — 2026-09-16

**Подтверждён условный P3: при `python -O` или `PYTHONOPTIMIZE=1` инструмент может записать `passed: true`, проверив только 1 из 4413 test-строк. Обычный запуск корректно отклоняет такой вход.**

Место: `scripts/verify_model_integration.py:40` — assert проверяет число строк, отсутствие пропущенных ожидаемых ID, допустимые prediction/SHAP ошибки; `:52` — assert проверяет время первых 100 объяснений. Под optimized Python эти assert не исполняются. Поле `passed=True` присваивается безусловно на строке 43, отчёт записывается на строке 54.

Воспроизведение использовало одну настоящую test-строку `51b158c8dfdb0cb9-000-base` из `resources/aml_dataset/behavior-v3/release/scenarios.jsonl`, полный настоящий `experiment-v2/evaluation/predictions.csv` с 4413 test-строками и настоящий scorer с пакетом `integration-v2-final`. Scorer, предсказания и функция verifier не подменялись. Полный датасет не копировался; модель не обучалась.

| Режим `.venv/Scripts/python.exe` | Код завершения | Выходной отчёт |
|---|---:|---|
| Без оптимизации | 1 | Не создан, `AssertionError` на строке 40 |
| `-O` | 0 | `passed: true`, `rows: 1` |
| `PYTHONOPTIMIZE=1` | 0 | `passed: true`, `rows: 1` |

Для обеих optimized-проб prediction error равен 0, SHAP residual — `1.4210854715202004e-14`. Таким образом, доказан обход проверки полноты данных, даже при правильном предсказании проверенной строки. Обход прочих проверок assert следует из конструкции кода; отдельные неверные prediction или искусственные задержки не внедрялись. Внутренние явные проверки самого scorer остаются действующими.

Все три отчёта направлялись в автоматически удаляемый временный каталог. Основной `model-integration.json` не открывался и не изменялся. SHA-256 `verify_model_integration.py` до/после совпал. Финальный код воспроизведения — **0**, `confirmed: true`.

Артефакты: [repro_optimized_verification.py](repro_optimized_verification.py), [optimized-verification.json](optimized-verification.json).

```powershell
$env:PYTHONUTF8 = '1'
.venv/Scripts/python.exe -B docs/verification/project-audit-2026-09-16/repro_optimized_verification.py
```

Рекомендация: обязательные quality gates выражать явным условием и исключением, действующим независимо от `__debug__`; `passed: true` формировать только после этих проверок. Как минимальную дополнительную защиту инструмент может отклонять optimized mode. Production-код не исправлялся. Дефект условный: результат полноценной проверки в обычном Python он не опровергает.
