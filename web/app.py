import os

from dotenv import load_dotenv
from flask import Flask

from web.auth import auth_bp, init_oauth
from web.db import init_db
from web.routes.admin import admin_bp
from web.routes.dashboard import dashboard_bp
from web.routes.jobs import jobs_bp
from web.routes.upload import upload_bp

load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # -------------------------------------------------------------------
    # Config
    # -------------------------------------------------------------------
    app.secret_key = os.environ["SECRET_KEY"]
    app.config["MAX_CONTENT_LENGTH"] = (
        int(os.environ.get("MAX_UPLOAD_MB", 500)) * 1024 * 1024
    )

    # -------------------------------------------------------------------
    # OAuth
    # -------------------------------------------------------------------
    init_oauth(app)

    # -------------------------------------------------------------------
    # Database
    # -------------------------------------------------------------------
    init_db()

    # -------------------------------------------------------------------
    # Blueprints
    # -------------------------------------------------------------------
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(upload_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(admin_bp)

    return app


# Gunicorn / flask run entry-point
app = create_app()
