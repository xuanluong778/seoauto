"""Security helpers: encryption, user scoping, roles."""

from app.core.secrets_crypto import decrypt_secret, encrypt_secret
from app.services.rbac import can_write, is_admin, normalize_role, normalize_status
from app.services.user_scope import belongs_to_user


def teardown_function():
    from app.core import secrets_crypto as sc

    sc._fernet.cache_clear()
    sc._fernets.cache_clear()


def test_encrypt_decrypt_roundtrip():
    plain = "sk-test-key-12345"
    stored = encrypt_secret(plain)
    assert stored.startswith("enc:v1:")
    assert decrypt_secret(stored) == plain


def test_decrypt_fallback_from_dev_default_key(monkeypatch):
    import base64
    import hashlib

    from cryptography.fernet import Fernet

    from app.core import secrets_crypto as sc

    digest = hashlib.sha256(b"secrets:change-this-in-production").digest()
    stored = "enc:v1:" + Fernet(base64.urlsafe_b64encode(digest)).encrypt(b"wp-app-pass-default").decode("ascii")
    monkeypatch.setenv("JWT_SECRET", "production-jwt-now")
    monkeypatch.delenv("SECRETS_MASTER_KEY", raising=False)
    sc._fernet.cache_clear()
    sc._fernets.cache_clear()
    assert sc.decrypt_secret(stored) == "wp-app-pass-default"


def test_decrypt_fallback_from_previous_jwt(monkeypatch):
    import base64
    import hashlib

    from cryptography.fernet import Fernet

    from app.core import secrets_crypto as sc

    old = "legacy-jwt-before-rotate"
    digest = hashlib.sha256(f"secrets:{old}".encode("utf-8")).digest()
    stored = "enc:v1:" + Fernet(base64.urlsafe_b64encode(digest)).encrypt(b"wp-app-pass-old").decode("ascii")
    monkeypatch.setenv("JWT_SECRET", "production-jwt-now")
    monkeypatch.setenv("JWT_SECRET_PREVIOUS", old)
    monkeypatch.delenv("SECRETS_MASTER_KEY", raising=False)
    sc._fernet.cache_clear()
    sc._fernets.cache_clear()
    assert sc.decrypt_secret(stored) == "wp-app-pass-old"


def test_legacy_plaintext_passthrough():
    assert decrypt_secret("plain-legacy-key") == "plain-legacy-key"


def test_belongs_to_user_rejects_other_user_and_legacy():
    assert belongs_to_user({"user_id": 1}, 1)
    assert not belongs_to_user({"user_id": 2}, 1)
    assert not belongs_to_user({}, 1)


def test_user_status():
    assert normalize_status("inactive") == "inactive"
    assert normalize_status("bad") == "active"


def test_roles():
    assert normalize_role("ADMIN") == "admin"
    assert is_admin(type("U", (), {"role": "admin"})())
    assert can_write(type("U", (), {"role": "viewer"})()) is False
    assert can_write(type("U", (), {"role": "editor"})()) is True


def test_api_key_stored_encrypted_roundtrip():
    enc = encrypt_secret("secret-key")
    assert enc.startswith("enc:v1:")
    assert decrypt_secret(enc) == "secret-key"
