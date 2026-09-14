"""
DB state-machine checks: terminal-state guard, cancel rules, page_done clamp,
task-id persistence. Needs deps installed:

    PYTHONPATH=. uv run python web/test_db.py
"""

import os
import tempfile

os.environ.setdefault("JOBS_DIR", tempfile.mkdtemp())

from web import db


def test_terminal_guard():
    db.init_db()
    db.create_job("guard-1", "u1", "U", "T", "bn", "now")
    db.update_status("guard-1", "DONE")

    # Terminal states are final — a late chord callback cannot resurrect.
    db.update_status("guard-1", "PROCESSING", page_total=10, page_done=5)
    job = db.get_job("guard-1")
    assert job["status"] == "DONE"
    assert job["page_total"] == 0 and job["page_done"] == 0


def test_cancel_rules():
    db.init_db()
    db.create_job("cancel-1", "u1", "U", "T", "bn", "now")
    assert db.cancel_job("cancel-1") is True
    # Already CANCELLED (terminal) — a second cancel is a no-op.
    assert db.cancel_job("cancel-1") is False

    db.create_job("cancel-2", "u1", "U", "T", "bn", "now")
    db.update_status("cancel-2", "DONE")
    assert db.cancel_job("cancel-2") is False


def test_increment_clamped():
    db.init_db()
    db.create_job("clamp-1", "u1", "U", "T", "bn", "now")
    db.update_status("clamp-1", "PROCESSING", page_total=2, page_done=0)
    for _ in range(5):  # more increments than pages (redelivery scenario)
        db.increment_page_done("clamp-1")
    assert db.get_job("clamp-1")["page_done"] == 2


def test_task_id_persistence():
    db.init_db()
    db.create_job("task-1", "u1", "U", "T", "bn", "now")
    db.set_celery_task_id("task-1", "celery-task-abc")
    assert db.get_job("task-1")["celery_task_id"] == "celery-task-abc"


if __name__ == "__main__":
    test_terminal_guard()
    test_cancel_rules()
    test_increment_clamped()
    test_task_id_persistence()
    print("ok")
