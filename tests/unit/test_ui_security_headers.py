from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_security_headers_and_russian_404():
    from src.aml_workshop_simulator.ui.nicegui.security_headers import install_security

    app = FastAPI()
    install_security(app, secure=True)
    with TestClient(app) as client:
        response = client.get('/missing-secret-like-path')
        assert response.status_code == 404
        assert 'Страница не найдена' in response.text
        assert '/missing-secret-like-path' not in response.text
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert response.headers['x-frame-options'] == 'DENY'
        assert response.headers['referrer-policy'] == 'strict-origin-when-cross-origin'
        assert 'max-age=' in response.headers['strict-transport-security']
        assert 'content-security-policy-report-only' in response.headers
        assert 'content-security-policy' not in response.headers


def test_local_http_does_not_set_hsts():
    from src.aml_workshop_simulator.ui.nicegui.security_headers import install_security

    app = FastAPI()
    install_security(app, secure=False)
    with TestClient(app) as client:
        assert 'strict-transport-security' not in client.get('/missing').headers
