from src.aml_workshop_simulator.core.expanded_game import expanded_game_config
from src.aml_workshop_simulator.domain.catalog import SEED_CARD_CATALOG
from src.aml_workshop_simulator.ui.nicegui.participant_limits import limits_view
from src.aml_workshop_simulator.services.editor_metadata import editor_metadata


def test_retired_limits_are_absent_from_ui_and_editor():
    config = expanded_game_config()
    config['constraints'].update(max_night_operations=0, max_anonymous_operations=0)
    config['constraints']['category_limits']['anonymous'] = '0.00'
    rows, *_ = limits_view(config, SEED_CARD_CATALOG)
    assert not any('ночн' in label.lower() or 'анонимн' in label.lower() for label, _ in rows)
    metadata = editor_metadata().model_dump()
    assert 'anonymous' not in metadata['quotas']
