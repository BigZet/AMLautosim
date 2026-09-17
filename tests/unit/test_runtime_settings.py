import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from src.aml_workshop_simulator.core.config import Settings


def test_database_components_preserve_special_characters(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    password = "space @:/?#%$&=+\\value"
    settings = Settings(_env_file=None, POSTGRES_PASSWORD=password)
    url = make_url(settings.database_url)
    assert url.password == password
    assert make_url(url.render_as_string(hide_password=False)).password == password


def test_explicit_database_url_overrides_components():
    url = "postgresql+asyncpg://test:encoded%40password@localhost:5433/disposable"
    settings = Settings(_env_file=None, DATABASE_URL=url, POSTGRES_PASSWORD="ignored")
    assert settings.database_url == url


@pytest.mark.parametrize(
    "name",
    ["SESSION_TTL_MINUTES", "LOGIN_MAX_FAILED_ATTEMPTS", "LOGIN_LOCKOUT_MINUTES"],
)
@pytest.mark.parametrize("value", [0, -1])
def test_auth_settings_reject_nonpositive_environment_values(monkeypatch, name, value):
    monkeypatch.setenv(name, str(value))
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None)
    assert any(
        detail["loc"] == (name,) and detail["type"] == "greater_than"
        for detail in error.value.errors()
    )


def test_auth_settings_accept_minimum_positive_values():
    settings = Settings(
        _env_file=None,
        SESSION_TTL_MINUTES=1,
        LOGIN_MAX_FAILED_ATTEMPTS=1,
        LOGIN_LOCKOUT_MINUTES=1,
    )
    assert settings.SESSION_TTL_MINUTES == 1
    assert settings.LOGIN_MAX_FAILED_ATTEMPTS == 1
    assert settings.LOGIN_LOCKOUT_MINUTES == 1
