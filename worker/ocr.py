"""
OCR module — wraps Google Cloud Document AI for per-page recognition.

Public API (called by Celery tasks):
  split_pages(job_id) -> int
      Converts the input PDF to per-page PNG images stored in
      /jobs/{job_id}/pages/page_{n:03d}.png.
      Returns the total number of pages.

  run_page(job_id, page_num, langs) -> None
      Sends the pre-rendered PNG for page_num to Document AI.
      Writes:
        /jobs/{job_id}/pages/page_{n:03d}.txt
        /jobs/{job_id}/pages/page_{n:03d}.html

Auth: Application Default Credentials. Set GOOGLE_APPLICATION_CREDENTIALS to a
service-account JSON key, or run `gcloud auth application-default login`.

Required env:
  DOCAI_PROJECT_ID    GCP project id
  DOCAI_LOCATION      processor location, "us" or "eu" (default "us")
  DOCAI_PROCESSOR_ID  Document AI OCR processor id
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

JOBS_DIR = os.environ.get("JOBS_DIR", "/jobs")

# Language code mapping from app hint → Document AI language hints.
# Document AI auto-detects script; hints only nudge ambiguous cases.
LANG_MAP: dict[str, list[str]] = {
    "bn": ["bn"],
    "ar": ["ar"],
    "en": ["en"],
    "mixed": ["bn", "ar", "en"],
}

_DOCAI_LOCATION = os.environ.get("DOCAI_LOCATION", "us")

# Client + processor name are cheap to build but reused across page tasks.
_client = None
_processor_name: str | None = None


def _get_client_and_processor():
    """Return (DocumentProcessorServiceClient, processor_resource_name), cached."""
    global _client, _processor_name
    if _client is not None:
        return _client, _processor_name

    from google.api_core.client_options import ClientOptions
    from google.cloud import documentai

    project_id = os.environ["DOCAI_PROJECT_ID"]
    processor_id = os.environ["DOCAI_PROCESSOR_ID"]

    opts = ClientOptions(
        api_endpoint=f"{_DOCAI_LOCATION}-documentai.googleapis.com"
    )
    _client = documentai.DocumentProcessorServiceClient(client_options=opts)
    _processor_name = _client.processor_path(
        project_id, _DOCAI_LOCATION, processor_id
    )
    logger.info("Document AI client ready: %s", _processor_name)
    return _client, _processor_name


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

    from pdf2image import convert_from_path

    logger.info("Converting PDF to images (dpi=150): %s", pdf_path)
    # dpi=150 keeps page images well under the Document AI 20 MB / 40 MP limit.
    images = convert_from_path(str(pdf_path), dpi=150)
    page_total = len(images)

    for idx, img in enumerate(images):
        page_num = idx + 1
        img_path = pages_dir / f"page_{page_num:03d}.png"
        img.save(str(img_path), format="PNG")
        logger.info("Saved page image %d/%d → %s", page_num, page_total, img_path)

    return page_total


def run_page(job_id: str, page_num: int, langs: list[str]) -> None:
    """Run Document AI OCR on a single pre-rendered page image.

    Reads  /jobs/{job_id}/pages/page_{page_num:03d}.png
    Writes /jobs/{job_id}/pages/page_{page_num:03d}.txt
           /jobs/{job_id}/pages/page_{page_num:03d}.html
    """
    from google.cloud import documentai

    pages_dir = Path(JOBS_DIR) / job_id / "pages"
    img_path = pages_dir / f"page_{page_num:03d}.png"

    if not img_path.exists():
        raise FileNotFoundError(
            f"Page image not found: {img_path}. split_pages() must run first."
        )

    logger.info("OCR page %d for job %s with langs %s", page_num, job_id, langs)
    client, processor_name = _get_client_and_processor()

    raw_doc = documentai.RawDocument(
        content=img_path.read_bytes(),
        mime_type="image/png",
    )
    process_options = documentai.ProcessOptions(
        ocr_config=documentai.OcrConfig(
            hints=documentai.OcrConfig.Hints(language_hints=langs)
        )
    )
    request = documentai.ProcessRequest(
        name=processor_name,
        raw_document=raw_doc,
        process_options=process_options,
    )

    result = client.process_document(request=request)
    txt_content, html_content = _page_outputs(result.document.text or "", page_num)

    (pages_dir / f"page_{page_num:03d}.txt").write_text(txt_content, encoding="utf-8")
    (pages_dir / f"page_{page_num:03d}.html").write_text(html_content, encoding="utf-8")

    logger.info("Page %d OCR complete for job %s", page_num, job_id)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _page_outputs(text: str, page_num: int) -> tuple[str, str]:
    """Turn Document AI page text into (txt, html) fragments.

    txt  — non-blank lines joined by newline.
    html — <div class="page"> with one escaped <p> per non-blank line.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    txt_content = "\n".join(lines)
    paragraphs = "\n".join(f"  <p>{_escape_html(ln)}</p>" for ln in lines)
    html_content = (
        f'<div class="page" data-page="{page_num}">\n'
        f"{paragraphs}\n"
        f"</div>"
    )
    return txt_content, html_content


def _escape_html(text: str) -> str:
    """Minimal HTML escaping for text block content."""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )
