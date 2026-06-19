import os
import sqlite3

from dotenv import load_dotenv

load_dotenv()

JOBS_DIR = os.environ["JOBS_DIR"]
DB_PATH = os.path.join(JOBS_DIR, "kitab.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the jobs table if it does not already exist."""
    os.makedirs(JOBS_DIR, exist_ok=True)
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id          TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL,
                user_name   TEXT,
                title       TEXT,
                lang_hint   TEXT,
                status      TEXT DEFAULT 'QUEUED',
                page_total  INTEGER DEFAULT 0,
                page_done   INTEGER DEFAULT 0,
                error_msg   TEXT,
                created_at  TEXT,
                updated_at  TEXT
            )
            """
        )
        conn.commit()


def create_job(
    id: str,
    user_id: str,
    user_name: str,
    title: str,
    lang_hint: str,
    created_at: str,
) -> None:
    """Insert a new job row."""
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO jobs (id, user_id, user_name, title, lang_hint, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'QUEUED', ?, ?)
            """,
            (id, user_id, user_name, title, lang_hint, created_at, created_at),
        )
        conn.commit()


def get_job(id: str) -> dict | None:
    """Return a single job as a dict, or None if not found."""
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (id,)).fetchone()
    return dict(row) if row else None


def get_jobs_by_user(user_id: str) -> list[dict]:
    """Return all jobs belonging to a user, newest first."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_jobs() -> list[dict]:
    """Return all jobs in the system, newest first (admin use)."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def update_status(
    id: str,
    status: str,
    page_done: int | None = None,
    page_total: int | None = None,
    error_msg: str | None = None,
) -> None:
    """Update job status and optional progress / error fields."""
    from datetime import datetime, timezone

    updated_at = datetime.now(timezone.utc).isoformat()

    fields = ["status = ?", "updated_at = ?"]
    values: list = [status, updated_at]

    if page_done is not None:
        fields.append("page_done = ?")
        values.append(page_done)
    if page_total is not None:
        fields.append("page_total = ?")
        values.append(page_total)
    if error_msg is not None:
        fields.append("error_msg = ?")
        values.append(error_msg)

    values.append(id)

    with _get_conn() as conn:
        conn.execute(
            f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        conn.commit()


def increment_page_done(id: str) -> None:
    """Atomically increment page_done by 1 and update updated_at.

    Safe to call from concurrent page-level Celery tasks.
    """
    from datetime import datetime, timezone

    updated_at = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET page_done = page_done + 1, updated_at = ? WHERE id = ?",
            (updated_at, id),
        )
        conn.commit()


def get_page_artifacts(job_id: str) -> list[dict]:
    """Return a list of page artifact dicts for a job.

    Each dict has:
      page_num  — 1-based page number
      has_txt   — True if page_NNN.txt exists
      has_html  — True if page_NNN.html exists
      done      — True if both txt and html exist

    Pages are returned in ascending page_num order.
    """
    import glob
    import re

    pages_dir = os.path.join(JOBS_DIR, job_id, "pages")
    if not os.path.isdir(pages_dir):
        return []

    # Discover all page numbers from txt files (authoritative)
    txt_paths = glob.glob(os.path.join(pages_dir, "page_*.txt"))
    page_nums: set[int] = set()
    for p in txt_paths:
        m = re.search(r"page_(\d+)\.txt$", p)
        if m:
            page_nums.add(int(m.group(1)))

    # Also discover from html files in case txt is missing
    html_paths = glob.glob(os.path.join(pages_dir, "page_*.html"))
    for p in html_paths:
        m = re.search(r"page_(\d+)\.html$", p)
        if m:
            page_nums.add(int(m.group(1)))

    results = []
    for n in sorted(page_nums):
        txt_exists = os.path.isfile(os.path.join(pages_dir, f"page_{n:03d}.txt"))
        html_exists = os.path.isfile(os.path.join(pages_dir, f"page_{n:03d}.html"))
        results.append(
            {
                "page_num": n,
                "has_txt": txt_exists,
                "has_html": html_exists,
                "done": txt_exists and html_exists,
            }
        )
    return results


def cancel_job(id: str) -> bool:
    """Mark a QUEUED, SPLITTING, or PROCESSING job as CANCELLED.

    Returns True if a row was actually updated.
    """
    from datetime import datetime, timezone

    updated_at = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE jobs
               SET status = 'CANCELLED', updated_at = ?
             WHERE id = ? AND status IN ('QUEUED', 'SPLITTING', 'PROCESSING')
            """,
            (updated_at, id),
        )
        conn.commit()
    return cur.rowcount > 0


def delete_job(id: str) -> bool:
    """Delete a FAILED or CANCELLED job row from the DB and remove its files.

    Returns True if a row was actually deleted.
    """
    import shutil

    with _get_conn() as conn:
        cur = conn.execute(
            """
            DELETE FROM jobs
             WHERE id = ? AND status IN ('FAILED', 'CANCELLED')
            """,
            (id,),
        )
        conn.commit()

    if cur.rowcount > 0:
        job_dir = os.path.join(JOBS_DIR, id)
        if os.path.isdir(job_dir):
            shutil.rmtree(job_dir, ignore_errors=True)
        return True
    return False
