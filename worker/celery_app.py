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
    task_soft_time_limit=3600,   # 1 hour soft kill (raises SoftTimeLimitExceeded)
    task_time_limit=7200,        # 2 hour hard kill
    worker_prefetch_multiplier=1,  # process one job at a time (CPU OCR mode)
    task_acks_late=True,           # ack after task completes, not before
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
)
