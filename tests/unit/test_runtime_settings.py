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
