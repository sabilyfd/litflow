import os
from functools import wraps

from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from web.db import get_user
from web.passwords import verify_password

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
    """Landing page — offers both OIDC and local username/password sign-in."""
    if "user_id" in session:
        return redirect(url_for("dashboard.index"))
    return render_template("login.html")


@auth_bp.route("/login/oidc")
def login_oidc():
    redirect_uri = os.environ["OIDC_REDIRECT_URI"]
    return oauth.pocket_id.authorize_redirect(redirect_uri)


@auth_bp.route("/login/password", methods=["POST"])
def login_password():
    """Authenticate a CLI-provisioned local account."""
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    user = get_user(username)
    if user is None or not verify_password(user["password_hash"], password):
        flash("Invalid username or password.", "error")
        return redirect(url_for("auth.login"))

    session.clear()
    # "local:" namespace keeps these ids from ever colliding with an OIDC `sub`.
    session["user_id"] = f"local:{username}"
    session["user_name"] = user["name"] or username
    session["user_email"] = user["email"] or ""
    session["is_admin"] = bool(user["is_admin"])
    return redirect(url_for("dashboard.index"))


@auth_bp.route("/auth/callback")
def callback():
    token = oauth.pocket_id.authorize_access_token()
    userinfo = token.get("userinfo") or oauth.pocket_id.userinfo(token=token)

    admin_group = os.environ.get("OIDC_ADMIN_GROUP", "admin")
    groups = userinfo.get("groups", [])

    session.clear()
    session["user_id"] = userinfo["sub"]
    session["user_name"] = userinfo.get("name") or userinfo.get("preferred_username", "")
    session["user_email"] = userinfo.get("email", "")
    session["is_admin"] = admin_group in groups

    return redirect(url_for("dashboard.index"))


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
