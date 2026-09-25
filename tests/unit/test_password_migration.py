import pytest
from passlib.hash import bcrypt_sha256

from src.aml_workshop_simulator.core import security


@pytest.mark.parametrize("password", ["ordinary-password", "Я🙂" * 64, "x" * 128])
def test_new_argon2id_and_legacy_passwords(password):
    current = security.get_password_hash(password)
    assert current.startswith("$argon2id$")
    assert security.verify_password(password, current)
    assert not security.verify_password(password + "wrong", current)
    assert not security.password_needs_rehash(current)
    legacy = bcrypt_sha256.hash(password)
    assert legacy.startswith("$bcrypt-sha256$v=2,")
    assert security.verify_password(password, legacy)
    assert not security.verify_password("wrong-password", legacy)
    assert security.password_needs_rehash(legacy)


@pytest.mark.parametrize(
    "encoded", ["", "broken", "$argon2id$invalid", "$bcrypt-sha256$bad"]
)
def test_malformed_hash_fails_closed(encoded):
    assert not security.verify_password("password", encoded)


def test_dual_reader_can_stage_before_enabling_new_writes(monkeypatch):
    from src.aml_workshop_simulator.core.config import settings

    current = security.get_password_hash("staged-password")
    monkeypatch.setattr(settings, "PASSWORD_ARGON2_ENABLED", False)
    legacy = security.get_password_hash("staged-password")
    assert legacy.startswith("$bcrypt-sha256$v=2,")
    assert security.verify_password("staged-password", current)
    assert security.verify_password("staged-password", legacy)
    assert not security.password_needs_rehash(legacy)
