import pytest

from scripts.seed_database import seed
from src.aml_workshop_simulator.core.config import settings


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
