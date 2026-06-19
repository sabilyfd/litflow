import os

from celery import Celery
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "kitab",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["worker.tasks"],
)

celery_app.conf.update(
    task_soft_time_limit=600,    # 10 min soft kill per page task
    task_time_limit=900,         # 15 min hard kill per page task
    task_track_started=True,     # required for chord fan-in correctness
    worker_prefetch_multiplier=1,  # process one task at a time per worker process
    task_acks_late=True,           # ack after task completes, not before
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
)
