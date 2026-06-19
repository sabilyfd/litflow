import os
from functools import wraps

import requests
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from flask import (
    Blueprint,
    redirect,
    session,
    url_for,
    current_app,
    g,
)

load_dotenv()

auth_bp = Blueprint("auth", __name__)
oauth = OAuth()


def init_oauth(app) -> None:
    """Register Authlib OAuth client on the Flask app."""
    oauth.init_app(app)
    oauth.register(
        name="pocket_id",
        client_id=os.environ["OIDC_CLIENT_ID"],
        client_secret=os.environ["OIDC_CLIENT_SECRET"],
        server_metadata_url=os.environ["OIDC_DISCOVERY_URL"],
        client_kwargs={"scope": "openid profile email"},
    )


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------


def login_required(f):
    """Redirect to /login if the user is not authenticated."""

    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)

    return decorated


def admin_required(f):
    """Return 403 if the user is not an admin."""

    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        if not session.get("is_admin"):
            return "Forbidden: admin access required.", 403
        return f(*args, **kwargs)

    return decorated


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@auth_bp.route("/login")
def login():
    redirect_uri = os.environ["OIDC_REDIRECT_URI"]
    return oauth.pocket_id.authorize_redirect(redirect_uri)


@auth_bp.route("/auth/callback")
def callback():
    token = oauth.pocket_id.authorize_access_token()
    userinfo = token.get("userinfo") or oauth.pocket_id.userinfo(token=token)

    admin_group = os.environ.get("OIDC_ADMIN_GROUP", "admin")
    groups = userinfo.get("groups", [])

    session["user_id"] = userinfo["sub"]
    session["user_name"] = userinfo.get("name") or userinfo.get("preferred_username", "")
    session["user_email"] = userinfo.get("email", "")
    session["is_admin"] = admin_group in groups

    return redirect(url_for("dashboard.index"))


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
