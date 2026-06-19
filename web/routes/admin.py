from flask import Blueprint, render_template, session

from web.auth import admin_required
from web.db import get_all_jobs

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/jobs")
@admin_required
def all_jobs():
    jobs = get_all_jobs()
    return render_template(
        "admin_jobs.html",
        jobs=jobs,
        user_name=session.get("user_name", ""),
        is_admin=True,
    )
