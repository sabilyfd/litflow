import json
import os
import uuid
from datetime import datetime, timezone

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from web.auth import login_required
from web.db import create_job

upload_bp = Blueprint("upload", __name__)

ALLOWED_EXTENSIONS = {"pdf"}
JOBS_DIR = os.environ.get("JOBS_DIR", "/jobs")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", 500))


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@upload_bp.route("/upload", methods=["GET"])
@login_required
def upload_form():
    return render_template(
        "upload.html",
        user_name=session.get("user_name", ""),
        is_admin=session.get("is_admin", False),
        max_mb=MAX_UPLOAD_MB,
    )


@upload_bp.route("/upload", methods=["POST"])
@login_required
def upload_file():
    # --- Validate file presence ---
    if "file" not in request.files:
        flash("No file part in the request.", "error")
        return redirect(url_for("upload.upload_form"))

    file = request.files["file"]
    title = request.form.get("title", "").strip()
    lang_hint = request.form.get("lang_hint", "bn")

    if not file or file.filename == "":
        flash("No file selected.", "error")
        return redirect(url_for("upload.upload_form"))

    if not title:
        flash("Book title is required.", "error")
        return redirect(url_for("upload.upload_form"))

    if not _allowed_file(file.filename):
        flash("Only PDF files are accepted.", "error")
        return redirect(url_for("upload.upload_form"))

    # --- Validate size ---
    file.seek(0, 2)  # seek to end
    file_size_mb = file.tell() / (1024 * 1024)
    file.seek(0)

    if file_size_mb > MAX_UPLOAD_MB:
        flash(f"File exceeds the {MAX_UPLOAD_MB} MB limit.", "error")
        return redirect(url_for("upload.upload_form"))

    # --- Create job ---
    job_id = str(uuid.uuid4())
    job_dir = os.path.join(JOBS_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    # Save PDF
    pdf_path = os.path.join(job_dir, "input.pdf")
    file.save(pdf_path)

    # Write meta.json
    created_at = datetime.now(timezone.utc).isoformat()
    meta = {
        "job_id": job_id,
        "title": title,
        "lang_hint": lang_hint,
        "user_id": session["user_id"],
        "user_name": session.get("user_name", ""),
        "created_at": created_at,
    }
    with open(os.path.join(job_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # Insert into DB
    create_job(
        id=job_id,
        user_id=session["user_id"],
        user_name=session.get("user_name", ""),
        title=title,
        lang_hint=lang_hint,
        created_at=created_at,
    )

    # Enqueue Celery task (import here to avoid circular deps)
    from worker.tasks import run_pipeline

    run_pipeline.delay(job_id)

    return redirect(url_for("jobs.job_status", job_id=job_id))
