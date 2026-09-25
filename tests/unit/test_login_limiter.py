import pytest


@pytest.mark.parametrize('side', ['api', 'ui'])
def test_invalid_proxy_network_rejected_at_startup(side):
    from pydantic import ValidationError
    from src.aml_workshop_simulator.core.config import Settings
    from src.aml_workshop_simulator.core.ui_config import UISettings

    cls, field = (Settings, 'AUTH_TRUSTED_UI_CIDRS') if side == 'api' else (UISettings, 'TRUSTED_PROXY_CIDRS')
    with pytest.raises(ValidationError):
        cls(_env_file=None, **{field: ['not-a-network']})


def test_nat_allows_sixty_registration_login_pairs():
    from src.aml_workshop_simulator.ui.nicegui.login_limiter import LoginLimiter

    limiter = LoginLimiter()
    for i in range(60):
        for _ in range(2):
            assert limiter.check('192.0.2.1', f'player{i}@example.com', now=1000) == 0
    assert limiter.check('192.0.2.1', 'extra@example.com', now=1000) > 0
    assert limiter.check('192.0.2.1', 'extra@example.com', now=1001) == 0


def test_pair_normalization_and_ip_isolation():
    from src.aml_workshop_simulator.ui.nicegui.login_limiter import LoginLimiter

    limiter = LoginLimiter()
    for _ in range(10):
        assert limiter.check('192.0.2.1', ' User@example.com ', now=1000) == 0
    assert limiter.check('192.0.2.1', 'user@example.com', now=1000) == 60
    assert limiter.check('192.0.2.2', 'user@example.com', now=1000) == 0
    assert limiter.check('192.0.2.1', 'user@example.com', now=1060) == 0


def test_proxy_headers_require_trusted_peer_and_signed_context():
    from src.aml_workshop_simulator.core.client_context import forwarded_client, sign_context, verify_context

    assert forwarded_client('192.0.2.7', '1.2.3.4', ['127.0.0.1/32']) == '192.0.2.7'
    assert forwarded_client('127.0.0.1', '1.2.3.4', ['127.0.0.1/32']) == '1.2.3.4'
    headers = sign_context('192.0.2.7', 'login', 'USER@example.com', 'secret', now=1000)
    assert verify_context(headers, 'login', 'user@example.com', 'secret', now=1001) == '192.0.2.7'
    assert verify_context(headers, 'login', 'other@example.com', 'secret', now=1001) is None
    assert verify_context(headers, 'login', 'user@example.com', 'wrong', now=1001) is None
    assert verify_context(headers, 'login', 'user@example.com', 'secret', now=1200) is None
