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
