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
from web.db import (
    CANCELLABLE_STATUSES,
    TERMINAL_STATUSES,
    cancel_job,
    delete_job,
    get_job,
    get_page_artifacts,
)

jobs_bp = Blueprint("jobs", __name__)

JOBS_DIR = os.environ.get("JOBS_DIR", "/jobs")

# Lightweight Celery client used only to revoke queued tasks
_celery = Celery(broker=os.environ.get("REDIS_URL", "redis://redis:6379/0"))

STATUS_COLORS = {
    "QUEUED": "gray",
    "SPLITTING": "blue",
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
        abort(409, description="Output is only available once the job is DONE.")

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
        abort(409, description="Output is only available once the job is DONE.")

    path = os.path.join(JOBS_DIR, job_id, "output.html")
    return send_file(path, as_attachment=True, download_name=f"{job_id}.html")


@jobs_bp.route("/jobs/<job_id>/view/html")
@login_required
def view_html(job_id: str):
    """Inline HTML output for the preview iframe — the download route above
    sends Content-Disposition: attachment, which an iframe cannot render."""
    job = get_job(job_id)
    if job is None:
        abort(404)
    _authorize_job(job)
    if job["status"] != "DONE":
        abort(409, description="Output is only available once the job is DONE.")

    path = os.path.join(JOBS_DIR, job_id, "output.html")
    return send_file(path, mimetype="text/html")


# ---------------------------------------------------------------------------
# Per-page artifact API
# ---------------------------------------------------------------------------

@jobs_bp.route("/jobs/<job_id>/pages")
@login_required
def pages_status(job_id: str):
    """JSON endpoint: returns per-page artifact availability.

    Called by the job_status page via fetch() to update the per-page grid
    without a full page reload.
    """
    from flask import jsonify
    job = get_job(job_id)
    if job is None:
        abort(404)
    _authorize_job(job)

    pages = get_page_artifacts(job_id)
    return jsonify({
        "status": job["status"],
        "page_total": job["page_total"],
        "page_done": job["page_done"],
        "pages": pages,
    })


@jobs_bp.route("/jobs/<job_id>/page/<int:page_num>/txt")
@login_required
def download_page_txt(job_id: str, page_num: int):
    """Download the .txt artifact for a single page."""
    job = get_job(job_id)
    if job is None:
        abort(404)
    _authorize_job(job)

    path = os.path.join(JOBS_DIR, job_id, "pages", f"page_{page_num:03d}.txt")
    if not os.path.isfile(path):
        abort(404)
    return send_file(
        path,
        as_attachment=True,
        download_name=f"{job_id}_page{page_num:03d}.txt",
        mimetype="text/plain",
    )


@jobs_bp.route("/jobs/<job_id>/page/<int:page_num>/html")
@login_required
def download_page_html(job_id: str, page_num: int):
    """Download the .html artifact for a single page."""
    job = get_job(job_id)
    if job is None:
        abort(404)
    _authorize_job(job)

    path = os.path.join(JOBS_DIR, job_id, "pages", f"page_{page_num:03d}.html")
    if not os.path.isfile(path):
        abort(404)
    return send_file(
        path,
        as_attachment=True,
        download_name=f"{job_id}_page{page_num:03d}.html",
        mimetype="text/html",
    )


@jobs_bp.route("/jobs/<job_id>/preview")
@login_required
def preview(job_id: str):
    job = get_job(job_id)
    if job is None:
        abort(404)
    _authorize_job(job)
    if job["status"] != "DONE":
        abort(409, description="Preview is only available once the job is DONE.")

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

    if job["status"] not in CANCELLABLE_STATUSES:
        flash("Only queued, splitting or processing jobs can be cancelled.", "error")
        return redirect(url_for("jobs.job_status", job_id=job_id))

    # Revoke the persisted Celery task id: the split task while it is queued,
    # or the chord callback once pages are dispatched. Page tasks already
    # running are not revoked individually — they observe the CANCELLED
    # status and skip, and update_status's terminal guard keeps the job
    # CANCELLED no matter what finishes afterwards.
    task_id = job.get("celery_task_id")
    if task_id:
        try:
            _celery.control.revoke(task_id, terminate=True, signal="SIGTERM")
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
