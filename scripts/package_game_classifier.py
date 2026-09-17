"""Package accepted weights and evidence without training or changing the dataset."""

import argparse
import json
from pathlib import Path
import shutil
from src.aml_workshop_simulator.services.game_classifier import (
    ROOT,
    INFERENCE_FILES,
    REQUIRED,
    file_hash,
)
from src.aml_workshop_simulator.services.aml_game_window_model_v2 import FEATURES

TITLES = [
    "Число получателей",
    "Доля расходов до поступлений",
    "Доля наличных",
    "Число отправителей",
    "Концентрация у одного получателя",
    "Второй возврат отправителю",
    "Третий возврат отправителю",
    "Число переводов",
    "Размер частей после поступлений",
    "Повторяемость сумм",
    "Совпадение поступлений и расходов",
    "Эпизоды распределения",
    "Эпизоды выдачи наличных",
    "Эпизоды расходов",
]


def package(dataset, model, output):
    if output.exists():
        raise ValueError("Output exists; packages are immutable")
    audit = json.loads((dataset / "audit.json").read_bytes())
    acceptance = json.loads((dataset / "acceptance.json").read_bytes())
    manifest = json.loads((model / "manifest.json").read_bytes())
    features, titles, inference_files = FEATURES, TITLES, INFERENCE_FILES
    extractor_version = manifest.get('extractor_version', 'aml-game-window-v2')
    if extractor_version == 'aml-game-attributes-context-v1':
        from src.aml_workshop_simulator.services.aml_game_attribute_features_v1 import FEATURES as contextual_features
        features = contextual_features
        titles = TITLES + [
            'Смена способов поступления', 'Смена страны банка отправителя',
            'Смена каналов переводов', 'Смена каналов снятия', 'Смена назначений операций',
            'Возвраты без соответствующего поступления', 'Возвраты в пределах поступившей суммы',
            'Согласованность общих расходов', 'Перевод оплаты услуг третьим лицам',
            'Наличные после поступления от операций с активами', 'Личные расходы после поступления',
            'Покупки в пределах зарплатных поступлений', 'Разнообразие способов поступления',
            'Смена целей снятия наличных',
        ]
        inference_files = (*INFERENCE_FILES, 'src/aml_workshop_simulator/services/aml_game_attribute_features_v1.py')
    if not acceptance["ready_for_training"] or acceptance[
        "source_manifest_sha256"
    ] != file_hash(dataset / "audit.json"):
        raise ValueError("Dataset not accepted")
    for name, expected in audit["artifact_hashes"].items():
        if file_hash(dataset / name) != expected:
            raise ValueError("Dataset drift: " + name)
    if manifest["dataset_hashes"] != audit["artifact_hashes"]:
        raise ValueError("Model/dataset mismatch")
    if manifest["inference_source_sha256"] != file_hash(ROOT / inference_files[-1]):
        raise ValueError("Inference source drift")
    output.mkdir(parents=True)
    for name in ("model.cbm", "manifest.json", "gameplay-audit.json"):
        shutil.copyfile(model / name, output / name)
    for name in ("context.json", "acceptance.json", "readback-audit.json"):
        shutil.copyfile(dataset / name, output / name)
    dictionary = dict(
        features=features,
        titles=dict(zip(features, titles)),
        descriptions={
            name: "Наблюдаемый признак цепочки. Неактивные признаки нормализованы по правилам учебной модели; вклад относится к логиту данного окна."
            for name in features
        },
    )
    (output / "features.json").write_text(
        json.dumps(dictionary, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )
    release = dict(
        format="aml-game-package-v1",
        files={name: file_hash(output / name) for name in sorted(REQUIRED)},
        inference_sources={name: file_hash(ROOT / name) for name in inference_files},
    )
    if extractor_version != 'aml-game-window-v2':
        release['extractor_version'] = extractor_version
    (output / "release.json").write_text(
        json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )
    from src.aml_workshop_simulator.services.game_classifier import GameClassifier

    classifier = GameClassifier(output)
    print(json.dumps(classifier.identity))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    package(args.dataset, args.model, args.output)
