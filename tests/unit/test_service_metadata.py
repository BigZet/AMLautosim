from unittest.mock import patch


def test_immutable_migration_heads_are_read_once():
    from src.aml_workshop_simulator.api.routers import health

    health._expected_heads.cache_clear()
    with patch('alembic.script.ScriptDirectory.get_heads', return_value=['head']) as read:
        assert health._expected_heads() == {'head'}
        assert health._expected_heads() == {'head'}
        assert read.call_count == 1
    health._expected_heads.cache_clear()


def test_http_and_openapi_use_one_service_version():
    import asyncio
    from src.aml_workshop_simulator.core.version import SERVICE_VERSION
    from src.aml_workshop_simulator.api.main import app
    from src.aml_workshop_simulator.api.routers.health import health_live

    assert app.version == SERVICE_VERSION
    assert asyncio.run(health_live())['version'] == SERVICE_VERSION
