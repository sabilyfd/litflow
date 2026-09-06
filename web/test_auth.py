"""
Local password-login check. Needs deps installed (flask, authlib, werkzeug):

    uv run python web/test_auth.py
"""

import os
import tempfile

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("JOBS_DIR", tempfile.mkdtemp())
os.environ.setdefault("OIDC_CLIENT_ID", "test")
os.environ.setdefault("OIDC_CLIENT_SECRET", "test")
os.environ.setdefault(
    "OIDC_DISCOVERY_URL", "https://example.com/.well-known/openid-configuration"
)
os.environ.setdefault("OIDC_REDIRECT_URI", "http://localhost/auth/callback")
os.environ.setdefault("SESSION_COOKIE_SECURE", "false")

from web import db
from web.app import create_app
from web.passwords import hash_password


def test_password_login():
    app = create_app()
    db.create_user("alice", hash_password("s3cret-pw"), "Alice", "a@example.com", True, "now")
    client = app.test_client()

    # wrong password → bounced back to /login, no session
    r = client.post("/login/password", data={"username": "alice", "password": "nope"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/login")
    with client.session_transaction() as s:
        assert "user_id" not in s

    # unknown user → same
    r = client.post("/login/password", data={"username": "ghost", "password": "x"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/login")

    # correct password → session populated, redirected to dashboard
    r = client.post("/login/password", data={"username": "alice", "password": "s3cret-pw"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/dashboard")
    with client.session_transaction() as s:
        assert s["user_id"] == "local:alice"
        assert s["is_admin"] is True
        assert s["user_name"] == "Alice"


if __name__ == "__main__":
    test_password_login()
    print("ok")
