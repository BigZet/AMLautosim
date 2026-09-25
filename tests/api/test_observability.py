from pydantic import SecretStr


def test_metrics_are_internal_and_logs_do_not_contain_credentials(
    api, monkeypatch, caplog
):
    from src.aml_workshop_simulator.core.config import settings

    monkeypatch.setattr(settings, "METRICS_TOKEN", SecretStr("metrics-test-secret"))
    assert api.get("/internal/metrics").status_code == 404
    with caplog.at_level("INFO", logger="aml.telemetry"):
        response = api.post(
            "/api/v1/auth/login",
            headers={"X-Request-ID": "safe-correlation"},
            json={
                "email": "private@example.com",
                "password": "secret-password",
                "audience": "play",
            },
        )
    assert response.status_code == 401
    assert response.headers["X-Request-ID"] != "safe-correlation"
    assert "safe-correlation" in caplog.text
    assert "secret-password" not in caplog.text
    assert "private@example.com" not in caplog.text
    response = api.get(
        "/internal/metrics", headers={"Authorization": "Bearer metrics-test-secret"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["histograms"]["sql_seconds"]["count"] > 0
    assert data["histograms"]["pool_acquire_seconds"]["count"] > 0
    assert data["histograms"]["http POST /api/v1/auth/login 401"]["count"] > 0
    assert "SELECT" not in response.text


def test_unknown_path_never_becomes_metric_label(api):
    from src.aml_workshop_simulator.core.observability import metrics

    api.get("/private-email@example.com")
    assert all("private-email" not in name for name in metrics.snapshot()["histograms"])


def test_readiness_error_logs_type_and_request_id_without_secret(api, caplog):
    from src.aml_workshop_simulator.db.session import get_db

    class Unavailable:
        async def execute(self, *args, **kwargs):
            raise RuntimeError('password=do-not-log-this session=private-token')

    async def unavailable():
        yield Unavailable()

    api.app.dependency_overrides[get_db] = unavailable
    try:
        with caplog.at_level('ERROR', logger='aml.telemetry'):
            response = api.get('/health/ready')
        assert response.status_code == 503
        assert response.headers['X-Request-ID'] in caplog.text
        assert 'RuntimeError' in caplog.text
        assert 'do-not-log-this' not in caplog.text
        assert 'private-token' not in caplog.text
        assert api.get('/health/live').status_code == 200
    finally:
        api.app.dependency_overrides.pop(get_db)
