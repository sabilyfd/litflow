"""
Cleaner / merger module.

merge(job_id):
  1. Reads all page_*.txt in sorted order → concatenates → output.txt
  2. Reads all page_*.html in sorted order → wraps in full HTML doc → output.html

The output.html wrapper includes minimal readable styling for serif fonts,
right-to-left/auto direction, and per-page dividers.
"""

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

JOBS_DIR = os.environ.get("JOBS_DIR", "/jobs")

OUTPUT_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="bn" dir="auto">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
  <style>
    body {{ font-family: serif; max-width: 800px; margin: auto; padding: 2rem; }}
    .page {{ margin-bottom: 2rem; border-bottom: 1px solid #ccc; }}
    p {{ line-height: 2; }}
  </style>
</head>
<body>
{pages}
</body>
</html>
"""


def merge(job_id: str) -> None:
    """
    Merge per-page OCR outputs into a single output.txt and output.html.

    Reads from /jobs/{job_id}/pages/
    Writes to  /jobs/{job_id}/output.txt
               /jobs/{job_id}/output.html
    """
    job_dir = Path(JOBS_DIR) / job_id
    pages_dir = job_dir / "pages"

    # --- Resolve book title ---
    title = job_id
    meta_path = job_dir / "meta.json"
    if meta_path.exists():
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        title = meta.get("title", job_id)

    # --- Collect page files in sorted order ---
    txt_files = sorted(pages_dir.glob("page_*.txt"))
    html_files = sorted(pages_dir.glob("page_*.html"))

    if not txt_files:
        raise FileNotFoundError(
            f"No page_*.txt files found in {pages_dir}. OCR may not have completed."
        )

    # --- Merge .txt ---
    logger.info("Merging %d text pages for job %s", len(txt_files), job_id)
    txt_parts: list[str] = []
    for txt_file in txt_files:
        content = txt_file.read_text(encoding="utf-8").strip()
        if content:
            txt_parts.append(content)

    output_txt = "\n\n".join(txt_parts)
    (job_dir / "output.txt").write_text(output_txt, encoding="utf-8")
    logger.info("output.txt written (%d chars)", len(output_txt))

    # --- Merge .html ---
    logger.info("Merging %d HTML pages for job %s", len(html_files), job_id)
    html_parts: list[str] = []
    for html_file in html_files:
        content = html_file.read_text(encoding="utf-8").strip()
        if content:
            html_parts.append(content)

    pages_block = "\n\n".join(html_parts)
    output_html = OUTPUT_HTML_TEMPLATE.format(
        title=_escape_html(title),
        pages=pages_block,
    )
    (job_dir / "output.html").write_text(output_html, encoding="utf-8")
    logger.info("output.html written (%d chars)", len(output_html))


def _escape_html(text: str) -> str:
    """Minimal HTML escaping for use in title tag."""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )
