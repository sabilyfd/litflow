import os

from celery import Celery
from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from web.auth import login_required
from web.db import cancel_job, delete_job, get_job

jobs_bp = Blueprint("jobs", __name__)

JOBS_DIR = os.environ.get("JOBS_DIR", "/jobs")

# Lightweight Celery client used only to revoke queued tasks
_celery = Celery(broker=os.environ.get("REDIS_URL", "redis://redis:6379/0"))

# Statuses that should stop the auto-refresh
TERMINAL_STATUSES = {"DONE", "FAILED", "CANCELLED"}

STATUS_COLORS = {
    "QUEUED": "gray",
    "PROCESSING": "blue",
    "OCR_DONE": "indigo",
    "CLEANING": "yellow",
    "DONE": "green",
    "FAILED": "red",
    "CANCELLED": "gray",
}


def _authorize_job(job: dict) -> None:
    """Abort 403 if the current user does not own the job and is not admin."""
    if session.get("is_admin"):
        return
    if job["user_id"] != session.get("user_id"):
        abort(403)


@jobs_bp.route("/jobs/<job_id>")
@login_required
def job_status(job_id: str):
    job = get_job(job_id)
    if job is None:
        abort(404)
    _authorize_job(job)

    auto_refresh = job["status"] not in TERMINAL_STATUSES
    color = STATUS_COLORS.get(job["status"], "gray")

    progress_pct = 0
    if job["page_total"] and job["page_total"] > 0:
        progress_pct = int(job["page_done"] / job["page_total"] * 100)

    return render_template(
        "job_status.html",
        job=job,
        color=color,
        auto_refresh=auto_refresh,
        progress_pct=progress_pct,
        user_name=session.get("user_name", ""),
        is_admin=session.get("is_admin", False),
    )


@jobs_bp.route("/jobs/<job_id>/download/txt")
@login_required
def download_txt(job_id: str):
    job = get_job(job_id)
    if job is None:
        abort(404)
    _authorize_job(job)
    if job["status"] != "DONE":
        abort(404)

    path = os.path.join(JOBS_DIR, job_id, "output.txt")
    return send_file(path, as_attachment=True, download_name=f"{job_id}.txt")


@jobs_bp.route("/jobs/<job_id>/download/html")
@login_required
def download_html(job_id: str):
    job = get_job(job_id)
    if job is None:
        abort(404)
    _authorize_job(job)
    if job["status"] != "DONE":
        abort(404)

    path = os.path.join(JOBS_DIR, job_id, "output.html")
    return send_file(path, as_attachment=True, download_name=f"{job_id}.html")


@jobs_bp.route("/jobs/<job_id>/preview")
@login_required
def preview(job_id: str):
    job = get_job(job_id)
    if job is None:
        abort(404)
    _authorize_job(job)
    if job["status"] != "DONE":
        abort(404)

    return render_template(
        "job_preview.html",
        job=job,
        user_name=session.get("user_name", ""),
        is_admin=session.get("is_admin", False),
    )


@jobs_bp.route("/jobs/<job_id>/cancel", methods=["POST"])
@login_required
def cancel(job_id: str):
    """Cancel a QUEUED or PROCESSING job."""
    job = get_job(job_id)
    if job is None:
        abort(404)
    _authorize_job(job)

    if job["status"] not in ("QUEUED", "PROCESSING"):
        flash("Only queued or processing jobs can be cancelled.", "error")
        return redirect(url_for("jobs.job_status", job_id=job_id))

    # Best-effort Celery revoke — task may already be running
    try:
        _celery.control.revoke(job_id, terminate=True, signal="SIGTERM")
    except Exception:
        pass

    if cancel_job(job_id):
        flash("Job cancelled.", "info")
    else:
        flash("Could not cancel job (it may have already changed state).", "error")

    return redirect(url_for("jobs.job_status", job_id=job_id))


@jobs_bp.route("/jobs/<job_id>/delete", methods=["POST"])
@login_required
def delete(job_id: str):
    """Permanently delete a FAILED or CANCELLED job and its files."""
    job = get_job(job_id)
    if job is None:
        abort(404)
    _authorize_job(job)

    if job["status"] not in ("FAILED", "CANCELLED"):
        flash("Only failed or cancelled jobs can be deleted.", "error")
        return redirect(url_for("jobs.job_status", job_id=job_id))

    if delete_job(job_id):
        flash("Job deleted.", "info")
        return redirect(url_for("dashboard.index"))

    flash("Could not delete job.", "error")
    return redirect(url_for("jobs.job_status", job_id=job_id))
