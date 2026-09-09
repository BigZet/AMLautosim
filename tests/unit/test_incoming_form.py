"""Render and edit the actual Streamlit card form against the API projection."""

from streamlit.testing.v1 import AppTest


def incoming_form():
    import streamlit as st

    from src.aml_workshop_simulator.core.game_config import base_game_config
    from src.aml_workshop_simulator.domain.catalog import CARD_CATALOG
    from src.aml_workshop_simulator.domain.game_models import card_spec_from_catalog
    from src.aml_workshop_simulator.domain.round_policy import RoundPolicy
    from src.aml_workshop_simulator.services.projections import card_out
    from src.aml_workshop_simulator.ui.participant.app import (
        default_step,
        render_step_form,
    )

    entry = next(c for c in CARD_CATALOG if c["code"] == "incoming_transfer")
    spec = card_spec_from_catalog(entry, 2)
    policy = RoundPolicy.from_config(base_game_config(), {spec.key: spec})
    card = card_out(spec, policy.for_card(spec.key)).model_dump(mode="json")
    st.session_state["rendered_step"] = render_step_form(
        card, default_step(card), "incoming_test"
    )


def test_incoming_form_exposes_sources_and_sender_without_legacy_frequency():
    from src.aml_workshop_simulator.schemas.scenarios import ScenarioStepIn

    app = AppTest.from_function(incoming_form).run()
    assert not app.exception
    assert len(app.number_input) == 1
    assert len(app.selectbox) == 2
    assert "Криптобиржа" in app.selectbox[0].options
    assert "Зарубежный банк — Кыргызстан (Киргизия)" in app.selectbox[0].options
    app.selectbox[0].select("foreign_bank_kg").run()
    app.selectbox[1].select("anonymous_established_account").run()
    assert not app.exception
    step = app.session_state["rendered_step"]
    ScenarioStepIn.model_validate(step)
    assert step["action_details"] == {
        "transfer_source": "foreign_bank_kg",
        "sender_relationship": "anonymous_established_account",
    }
    assert step["context"]["channel"] == "bank"
    assert "frequency" not in step


def incoming_admin_editor():
    import json
    from dataclasses import asdict

    import streamlit as st

    from src.aml_workshop_simulator.core.game_config import base_game_config
    from src.aml_workshop_simulator.domain.catalog import CARD_CATALOG
    from src.aml_workshop_simulator.domain.game_models import card_spec_from_catalog
    from src.aml_workshop_simulator.services.projections import card_out
    from src.aml_workshop_simulator.ui.admin.config_editor import render_editor

    specs = [card_spec_from_catalog(c, i) for i, c in enumerate(CARD_CATALOG, 1)]
    config = base_game_config()
    config["card_snapshots"] = json.loads(
        json.dumps([asdict(s) for s in specs], default=str)
    )
    catalog = [card_out(s).model_dump(mode="json") for s in specs]
    assert all(len(card["visible_params"]) <= 2 for card in catalog)
    st.session_state["edited_config"] = render_editor(config, catalog)


def test_admin_editor_handles_new_frozen_card_and_current_occurrence_limit():
    from src.aml_workshop_simulator.schemas.round_config import GameConfigIn

    app = AppTest.from_function(incoming_admin_editor).run()
    assert not app.exception
    config = app.session_state["edited_config"]
    GameConfigIn.model_validate(config)
    incoming = next(o for o in config["operations"] if o["code"] == "incoming_transfer")
    assert incoming["max_occurrences"] == 3
    assert incoming["visible_params"] == [
        "action.transfer_source",
        "action.sender_relationship",
    ]
    assert incoming["defaults"]["channel"] == "bank"
    assert "show_frequency" not in incoming
