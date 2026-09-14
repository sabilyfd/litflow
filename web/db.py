import os
import sqlite3
from contextlib import closing

JOBS_DIR = os.environ["JOBS_DIR"]
DB_PATH = os.path.join(JOBS_DIR, "kitab.db")

# A job in a terminal status is never rewritten (update_status, cancel_job) —
# this is what stops a cancelled/failed job from resurrecting to DONE.
TERMINAL_STATUSES = ("DONE", "FAILED", "CANCELLED")
CANCELLABLE_STATUSES = ("QUEUED", "SPLITTING", "PROCESSING")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # The same file is written by two gunicorn workers and the Celery worker;
    # WAL + busy_timeout avoid spurious "database is locked" errors.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    """Create the jobs and users tables if they do not already exist."""
    os.makedirs(JOBS_DIR, exist_ok=True)
    with closing(_get_conn()) as conn:
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
                updated_at  TEXT,
                celery_task_id TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username      TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                name          TEXT,
                email         TEXT,
                is_admin      INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT NOT NULL
            )
            """
        )
        # Pre-existing dev databases predate the task-id column.
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        if "celery_task_id" not in cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN celery_task_id TEXT")
        conn.commit()


# ---------------------------------------------------------------------------
# Local user accounts (created via the `flask user` CLI only — no signup route)
# ---------------------------------------------------------------------------

def create_user(
    username: str,
    password_hash: str,
    name: str,
    email: str,
    is_admin: bool,
    created_at: str,
) -> None:
    """Insert a local user. Raises sqlite3.IntegrityError if username exists."""
    with closing(_get_conn()) as conn:
        conn.execute(
            """
            INSERT INTO users (username, password_hash, name, email, is_admin, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (username, password_hash, name, email, 1 if is_admin else 0, created_at),
        )
        conn.commit()


def get_user(username: str) -> dict | None:
    """Return a local user row as a dict, or None."""
    with closing(_get_conn()) as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
    return dict(row) if row else None


def list_users() -> list[dict]:
    """Return all local users, oldest first."""
    with closing(_get_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY created_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def set_user_password(username: str, password_hash: str) -> bool:
    """Replace a local user's password hash. Returns True if a row changed."""
    with closing(_get_conn()) as conn:
        cur = conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (password_hash, username),
        )
        conn.commit()
    return cur.rowcount > 0


def delete_user(username: str) -> bool:
    """Delete a local user. Returns True if a row was removed."""
    with closing(_get_conn()) as conn:
        cur = conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.commit()
    return cur.rowcount > 0


def create_job(
    id: str,
    user_id: str,
    user_name: str,
    title: str,
    lang_hint: str,
    created_at: str,
) -> None:
    """Insert a new job row."""
    with closing(_get_conn()) as conn:
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
    with closing(_get_conn()) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (id,)).fetchone()
    return dict(row) if row else None


def get_jobs_by_user(user_id: str) -> list[dict]:
    """Return all jobs belonging to a user, newest first."""
    with closing(_get_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_jobs() -> list[dict]:
    """Return all jobs in the system, newest first (admin use)."""
    with closing(_get_conn()) as conn:
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
    """Update job status and optional progress / error fields.

    Terminal states are final: writes against a DONE/FAILED/CANCELLED job are
    dropped, so a chord callback finishing after a cancel or page failure
    cannot resurrect the job.
    """
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

    placeholders = ", ".join("?" for _ in TERMINAL_STATUSES)
    values.append(id)
    values.extend(TERMINAL_STATUSES)

    with closing(_get_conn()) as conn:
        conn.execute(
            f"UPDATE jobs SET {', '.join(fields)} "
            f"WHERE id = ? AND status NOT IN ({placeholders})",
            values,
        )
        conn.commit()


def set_celery_task_id(id: str, task_id: str) -> None:
    """Persist the job's current Celery task id (the split task, later the
    chord callback id) so cancel can revoke a real task."""
    with closing(_get_conn()) as conn:
        conn.execute(
            "UPDATE jobs SET celery_task_id = ? WHERE id = ?",
            (task_id, id),
        )
        conn.commit()


def increment_page_done(id: str) -> None:
    """Atomically increment page_done by 1 and update updated_at.

    Safe to call from concurrent page-level Celery tasks. MIN clamps the
    count at page_total so redelivered tasks (task_acks_late) cannot push
    progress past 100%.
    """
    from datetime import datetime, timezone

    updated_at = datetime.now(timezone.utc).isoformat()
    with closing(_get_conn()) as conn:
        conn.execute(
            "UPDATE jobs SET page_done = MIN(page_done + 1, page_total),"
            " updated_at = ? WHERE id = ?",
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
    placeholders = ", ".join("?" for _ in CANCELLABLE_STATUSES)
    with closing(_get_conn()) as conn:
        cur = conn.execute(
            f"""
            UPDATE jobs
               SET status = 'CANCELLED', updated_at = ?
             WHERE id = ? AND status IN ({placeholders})
            """,
            (updated_at, id, *CANCELLABLE_STATUSES),
        )
        conn.commit()
    return cur.rowcount > 0


def delete_job(id: str) -> bool:
    """Delete a FAILED or CANCELLED job row from the DB and remove its files.

    Returns True if a row was actually deleted.
    """
    import shutil

    with closing(_get_conn()) as conn:
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
