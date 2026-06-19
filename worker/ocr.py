"""
OCR module — wraps Surya OCR for CPU-mode inference.

Public API (called by Celery tasks):
  split_pages(job_id) -> int
      Converts the input PDF to per-page PNG images stored in
      /jobs/{job_id}/pages/page_{n:03d}.png.
      Returns the total number of pages.

  run_page(job_id, page_num, langs) -> None
      Runs Surya OCR on the pre-rendered PNG for page_num.
      Writes:
        /jobs/{job_id}/pages/page_{n:03d}.txt
        /jobs/{job_id}/pages/page_{n:03d}.html

Surya models are cached at module level (loaded once per worker process,
reused for every subsequent page task on the same process).
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from pdf2image import convert_from_path

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

# ---------------------------------------------------------------------------
# Module-level model cache — loaded once per worker process on first use.
# ---------------------------------------------------------------------------
_MODELS: dict = {}


def _get_models() -> tuple:
    """Return (det_model, det_processor, rec_model, rec_processor).

    Models are loaded from disk on the first call and then cached in
    _MODELS for the lifetime of the worker process.
    """
    global _MODELS
    if _MODELS:
        return (
            _MODELS["det_model"],
            _MODELS["det_processor"],
            _MODELS["rec_model"],
            _MODELS["rec_processor"],
        )

    logger.info("Loading Surya models (first use in this worker process)…")

    from surya.model.detection.model import load_model as load_det_model
    from surya.model.detection.model import load_processor as load_det_processor
    from surya.model.recognition.model import load_model as load_rec_model
    from surya.model.recognition.processor import load_processor as load_rec_processor

    _MODELS["det_model"] = load_det_model()
    _MODELS["det_processor"] = load_det_processor()
    _MODELS["rec_model"] = load_rec_model()
    _MODELS["rec_processor"] = load_rec_processor()

    logger.info("Surya models loaded and cached.")
    return (
        _MODELS["det_model"],
        _MODELS["det_processor"],
        _MODELS["rec_model"],
        _MODELS["rec_processor"],
    )


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def split_pages(job_id: str) -> int:
    """Convert the PDF to per-page PNG images.

    Writes /jobs/{job_id}/pages/page_{n:03d}.png for every page.
    Returns the total page count.
    """
    job_dir = Path(JOBS_DIR) / job_id
    pdf_path = job_dir / "input.pdf"
    pages_dir = job_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Converting PDF to images (dpi=150): %s", pdf_path)
    # dpi=150 gives a good speed/quality balance for CPU Surya inference.
    images = convert_from_path(str(pdf_path), dpi=150)
    page_total = len(images)

    for idx, img in enumerate(images):
        page_num = idx + 1
        img_path = pages_dir / f"page_{page_num:03d}.png"
        img.save(str(img_path), format="PNG")
        logger.info("Saved page image %d/%d → %s", page_num, page_total, img_path)

    return page_total


def run_page(job_id: str, page_num: int, langs: list[str]) -> None:
    """Run Surya OCR on a single pre-rendered page image.

    Reads  /jobs/{job_id}/pages/page_{page_num:03d}.png
    Writes /jobs/{job_id}/pages/page_{page_num:03d}.txt
           /jobs/{job_id}/pages/page_{page_num:03d}.html
    """
    from PIL import Image
    from surya.ocr import run_ocr

    pages_dir = Path(JOBS_DIR) / job_id / "pages"
    img_path = pages_dir / f"page_{page_num:03d}.png"

    if not img_path.exists():
        raise FileNotFoundError(
            f"Page image not found: {img_path}. split_pages() must run first."
        )

    logger.info("OCR page %d for job %s with langs %s", page_num, job_id, langs)
    image = Image.open(str(img_path))

    det_model, det_processor, rec_model, rec_processor = _get_models()

    # batch_size=1: CPU-safe sequential inference; avoids the default large batch
    # that makes recognition extremely slow on CPU.
    results = run_ocr(
        [image],
        [langs],
        det_model,
        det_processor,
        rec_model,
        rec_processor,
        batch_size=1,
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

    (pages_dir / f"page_{page_num:03d}.txt").write_text(txt_content, encoding="utf-8")
    (pages_dir / f"page_{page_num:03d}.html").write_text(html_content, encoding="utf-8")

    logger.info("Page %d OCR complete for job %s", page_num, job_id)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _escape_html(text: str) -> str:
    """Minimal HTML escaping for text block content."""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )
