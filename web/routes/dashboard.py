from flask import Blueprint, render_template, session

from web.auth import login_required
from web.db import get_all_jobs, get_jobs_by_user

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@dashboard_bp.route("/dashboard")
@login_required
def index():
    is_admin = session.get("is_admin", False)
    if is_admin:
        jobs = get_all_jobs()
    else:
        jobs = get_jobs_by_user(session["user_id"])

    return render_template(
        "dashboard.html",
        jobs=jobs,
        is_admin=is_admin,
        user_name=session.get("user_name", ""),
    )
