import pytest

from scripts.seed_database import seed
from src.aml_workshop_simulator.core.config import settings


@pytest.fixture
def seeded_game_version():
    return 10


@pytest.mark.parametrize("password", ["", "short", "x" * 129])
def test_new_admin_requires_valid_explicit_password(api, sql, monkeypatch, password):
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_EMAIL", "new-admin@example.com")
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_PASSWORD", password)
    with pytest.raises(ValueError, match="BOOTSTRAP_ADMIN_PASSWORD"):
        api.portal.call(seed)
    assert sql("SELECT id FROM users WHERE email = 'new-admin@example.com'") == []


def test_seed_preserves_existing_admin_without_password(api, sql, monkeypatch):
    before = sql("SELECT id, hashed_password FROM users ORDER BY id")
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_PASSWORD", "")
    api.portal.call(seed)
    assert sql("SELECT id, hashed_password FROM users ORDER BY id") == before


def test_bootstrap_without_demo_leaves_empty_game_for_api_creation(api, sql):
    # This database belongs to the test fixture, not to a live game instance.
    sql("TRUNCATE rounds RESTART IDENTITY CASCADE")
    first = api.portal.call(lambda: seed(create_demo_round=False))
    second = api.portal.call(lambda: seed(create_demo_round=False))
    assert first == second
    assert first["cards"] > 0 and first["admin_id"] > 0
    assert first["round_id"] is None and first["round_status"] is None
    assert sql("SELECT id FROM rounds") == []
    assert sql("SELECT count(*) AS n FROM users")[0]["n"] == 1


def test_no_demo_bootstrap_preserves_existing_game_and_audit(api, sql):
    before = sql("SELECT * FROM rounds ORDER BY id")
    events = sql("SELECT * FROM audit_events ORDER BY id")
    api.portal.call(lambda: seed(create_demo_round=False))
    assert sql("SELECT * FROM rounds ORDER BY id") == before
    assert sql("SELECT * FROM audit_events ORDER BY id") == events


def test_v10_startup_does_not_require_legacy_package(api, monkeypatch):
    from fastapi.testclient import TestClient
    from src.aml_workshop_simulator.api.main import create_app
    from src.aml_workshop_simulator.services import model_scoring

    def unavailable():
        raise AssertionError("Unneeded legacy model was loaded")

    monkeypatch.setattr(model_scoring, "get_model_scorer", unavailable)
    with TestClient(create_app()) as client:
        assert client.get("/health/ready").status_code == 200


def test_readiness_checks_saved_round_package(api, monkeypatch):
    from src.aml_workshop_simulator.services import model_scoring
    from src.aml_workshop_simulator.core.errors import Conflict

    checked = []

    def unavailable(config):
        checked.append(config["risk_model"])
        raise Conflict("Missing saved package", code="model_unavailable")

    monkeypatch.setattr(model_scoring, "get_round_scorer", unavailable)
    response = api.get("/health/ready")
    assert response.status_code == 503
    assert checked
    assert response.json()["checks"]["round_model"]["status"] == "unavailable"


def test_liveness_never_opens_database_or_model(api, monkeypatch):
    from src.aml_workshop_simulator.services import game_classifier
    from src.aml_workshop_simulator.db.session import get_db

    def forbidden():
        raise AssertionError("Liveness accessed a dependency")

    monkeypatch.setattr(game_classifier, "get_game_classifier", forbidden)
    api.app.dependency_overrides[get_db] = forbidden
    try:
        assert api.get("/health/live").status_code == 200
    finally:
        api.app.dependency_overrides.pop(get_db)


def test_no_demo_bootstrap_cannot_be_combined_with_reset(api, sql):
    before = sql("SELECT * FROM rounds ORDER BY id")
    with pytest.raises(ValueError, match="reset"):
        api.portal.call(lambda: seed(reset_game=True, create_demo_round=False))
    assert sql("SELECT * FROM rounds ORDER BY id") == before
