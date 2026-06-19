"""
Celery task definitions for the fan-out / fan-in OCR pipeline.

Flow:
  1. split_pdf      — converts PDF to per-page PNGs, sets page_total,
                      dispatches a chord: group(ocr_page × N) | merge_job
  2. ocr_page       — OCRs one page PNG, writes txt+html, increments page_done
  3. merge_job      — assembles output.txt + output.html, marks job DONE

  (old run_pipeline kept as a stub for safety during rolling deploys)
"""

import logging

from celery import chord, group

from worker.celery_app import celery_app
from worker import ocr, cleaner
from web.db import increment_page_done, update_status

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. split_pdf — entry point dispatched from the web upload route
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, name="worker.tasks.split_pdf")
def split_pdf(self, job_id: str) -> None:
    """Split the PDF into per-page PNG images, then fan out one ocr_page task per page.

    Uses a Celery chord so merge_job fires automatically when all pages are done.
    """
    logger.info("split_pdf starting for job %s", job_id)
    try:
        update_status(job_id, "SPLITTING")

        page_total = ocr.split_pages(job_id)

        update_status(job_id, "PROCESSING", page_total=page_total, page_done=0)

        # Read lang_hint from meta.json
        import json
        import os
        from pathlib import Path
        JOBS_DIR = os.environ.get("JOBS_DIR", "/jobs")
        meta_path = Path(JOBS_DIR) / job_id / "meta.json"
        lang_hint = "bn"
        if meta_path.exists():
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            lang_hint = meta.get("lang_hint", "bn")

        from worker.ocr import LANG_MAP
        langs = LANG_MAP.get(lang_hint, ["bn"])

        # Build chord: fan-out N page tasks → fan-in merge_job callback
        page_tasks = group(
            ocr_page.s(job_id, page_num, langs)
            for page_num in range(1, page_total + 1)
        )
        pipeline = chord(page_tasks)(merge_job.s(job_id))
        logger.info(
            "split_pdf dispatched chord for job %s: %d pages, chord id %s",
            job_id, page_total, pipeline.id,
        )

    except Exception as exc:
        logger.exception("split_pdf failed for job %s: %s", job_id, exc)
        update_status(job_id, "FAILED", error_msg=str(exc))
        raise


# ---------------------------------------------------------------------------
# 2. ocr_page — one task per page
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, name="worker.tasks.ocr_page")
def ocr_page(self, job_id: str, page_num: int, langs: list[str]) -> None:
    """Run OCR on a single pre-rendered page image.

    Writes page_NNN.txt and page_NNN.html, then atomically increments page_done.
    """
    logger.info("ocr_page starting: job=%s page=%d langs=%s", job_id, page_num, langs)
    try:
        ocr.run_page(job_id, page_num, langs)
        increment_page_done(job_id)
        logger.info("ocr_page done: job=%s page=%d", job_id, page_num)
    except Exception as exc:
        logger.exception(
            "ocr_page failed: job=%s page=%d: %s", job_id, page_num, exc
        )
        update_status(job_id, "FAILED", error_msg=f"Page {page_num}: {exc}")
        raise


# ---------------------------------------------------------------------------
# 3. merge_job — chord callback, fires when all ocr_page tasks finish
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, name="worker.tasks.merge_job")
def merge_job(self, results: list, job_id: str) -> None:
    """Merge all per-page outputs into output.txt + output.html.

    ``results`` is the list of return values from the ocr_page chord group
    (all None since ocr_page returns nothing); it is ignored.
    """
    logger.info("merge_job starting for job %s", job_id)
    try:
        update_status(job_id, "CLEANING")
        cleaner.merge(job_id)
        update_status(job_id, "DONE")
        logger.info("merge_job complete for job %s", job_id)
    except Exception as exc:
        logger.exception("merge_job failed for job %s: %s", job_id, exc)
        update_status(job_id, "FAILED", error_msg=str(exc))
        raise


# ---------------------------------------------------------------------------
# Legacy stub — kept so any in-flight tasks dispatched under the old name
# don't crash the worker during a rolling restart.
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, name="worker.tasks.run_pipeline")
def run_pipeline(self, job_id: str) -> None:
    """Deprecated: redirect to split_pdf for backwards compatibility."""
    logger.warning(
        "run_pipeline (deprecated) called for job %s — redirecting to split_pdf",
        job_id,
    )
    split_pdf.apply_async(args=[job_id])
