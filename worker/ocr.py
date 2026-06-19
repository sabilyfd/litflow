"""
OCR module — wraps Surya OCR for CPU-mode inference.

For each page of the input PDF:
  - Converts the page to a PIL image via pdf2image
  - Runs Surya OCR (text recognition)
  - Writes /jobs/{job_id}/pages/page_{n:03d}.txt
  - Writes /jobs/{job_id}/pages/page_{n:03d}.html
  - Updates DB with page_total and incremental page_done
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from pdf2image import convert_from_path

from web.db import update_status

load_dotenv()

logger = logging.getLogger(__name__)

JOBS_DIR = os.environ.get("JOBS_DIR", "/jobs")

# Language code mapping from app hint → Surya language list
LANG_MAP: dict[str, list[str]] = {
    "bn": ["bn"],
    "ar": ["ar"],
    "en": ["en"],
    "mixed": ["bn", "ar", "en"],
}


def _load_surya_models():
    """Lazy-load Surya models (downloads on first run, ~1-2 GB)."""
    # Import here to avoid loading models at module import time
    from surya.model.detection.model import load_model as load_det_model
    from surya.model.detection.model import load_processor as load_det_processor
    from surya.model.recognition.model import load_model as load_rec_model
    from surya.model.recognition.processor import load_processor as load_rec_processor

    det_model = load_det_model()
    det_processor = load_det_processor()
    rec_model = load_rec_model()
    rec_processor = load_rec_processor()

    return det_model, det_processor, rec_model, rec_processor


def run(job_id: str) -> None:
    """
    Run Surya OCR on the PDF for the given job.

    Outputs:
      /jobs/{job_id}/pages/page_{n:03d}.txt
      /jobs/{job_id}/pages/page_{n:03d}.html
    """
    job_dir = Path(JOBS_DIR) / job_id
    pdf_path = job_dir / "input.pdf"
    pages_dir = job_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    # Read meta.json for lang_hint
    import json
    meta_path = job_dir / "meta.json"
    lang_hint = "bn"
    if meta_path.exists():
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        lang_hint = meta.get("lang_hint", "bn")

    langs = LANG_MAP.get(lang_hint, ["bn"])

    logger.info("Converting PDF to images: %s", pdf_path)
    images = convert_from_path(str(pdf_path))
    page_total = len(images)

    # Write page_total to DB
    update_status(job_id, "PROCESSING", page_total=page_total, page_done=0)

    logger.info("Loading Surya models…")
    det_model, det_processor, rec_model, rec_processor = _load_surya_models()

    from surya.ocr import run_ocr

    logger.info("Starting OCR on %d pages with langs %s", page_total, langs)

    for idx, image in enumerate(images):
        page_num = idx + 1
        logger.info("OCR page %d/%d", page_num, page_total)

        # Run Surya OCR on this single image
        results = run_ocr(
            [image],
            [langs],
            det_model,
            det_processor,
            rec_model,
            rec_processor,
        )

        page_result = results[0]  # one image → one result

        # --- Build text output ---
        lines = [line.text for line in page_result.text_lines if line.text.strip()]
        txt_content = "\n".join(lines)

        # --- Build HTML output ---
        paragraphs = "\n".join(
            f"  <p>{_escape_html(line.text)}</p>"
            for line in page_result.text_lines
            if line.text.strip()
        )
        html_content = (
            f'<div class="page" data-page="{page_num}">\n'
            f"{paragraphs}\n"
            f"</div>"
        )

        # Write files
        (pages_dir / f"page_{page_num:03d}.txt").write_text(
            txt_content, encoding="utf-8"
        )
        (pages_dir / f"page_{page_num:03d}.html").write_text(
            html_content, encoding="utf-8"
        )

        # Update progress
        update_status(job_id, "PROCESSING", page_done=page_num)

    logger.info("OCR complete for job %s", job_id)


def _escape_html(text: str) -> str:
    """Minimal HTML escaping for text block content."""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )
