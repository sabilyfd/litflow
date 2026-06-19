import logging

from worker.celery_app import celery_app
from worker import ocr, cleaner
from web.db import update_status

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="worker.tasks.run_pipeline")
def run_pipeline(self, job_id: str) -> None:
    """
    Main OCR pipeline task.

    Steps:
      1. Mark job as PROCESSING
      2. Run Surya OCR (writes per-page txt/html)
      3. Mark job as OCR_DONE
      4. Run cleaner merge (writes output.txt + output.html)
      5. Mark job as CLEANING then DONE
    On any exception: mark job as FAILED with error message.
    """
    logger.info("Starting pipeline for job %s", job_id)

    try:
        update_status(job_id, "PROCESSING")

        ocr.run(job_id)

        update_status(job_id, "OCR_DONE")

        update_status(job_id, "CLEANING")
        cleaner.merge(job_id)

        update_status(job_id, "DONE")
        logger.info("Pipeline complete for job %s", job_id)

    except Exception as exc:
        logger.exception("Pipeline failed for job %s: %s", job_id, exc)
        update_status(job_id, "FAILED", error_msg=str(exc))
        raise  # re-raise so Celery marks task as FAILURE
