"""Merge ordering check, esp. books over 999 pages. Needs deps installed:

    PYTHONPATH=. uv run python worker/test_cleaner.py
"""

import tempfile
from pathlib import Path

from worker import cleaner


def test_merge_orders_pages_numerically():
    root = Path(tempfile.mkdtemp())
    job_id = "sortcheck"
    pages = root / job_id / "pages"
    pages.mkdir(parents=True)

    # Deliberately out of order; page_1000 sorts between page_100 and
    # page_101 lexically but is the last page numerically.
    page_text = {1: "one", 2: "two", 100: "hundred", 101: "hundred-one", 1000: "thousand"}
    for n, text in page_text.items():
        (pages / f"page_{n:03d}.txt").write_text(text, encoding="utf-8")
        (pages / f"page_{n:03d}.html").write_text(
            f'<div class="page" data-page="{n}">\n  <p>{text}</p>\n</div>',
            encoding="utf-8",
        )

    cleaner.JOBS_DIR = str(root)
    cleaner.merge(job_id)

    job_dir = root / job_id
    txt = (job_dir / "output.txt").read_text(encoding="utf-8")
    assert txt == "\n\n".join(
        ["one", "two", "hundred", "hundred-one", "thousand"]
    )

    html = (job_dir / "output.html").read_text(encoding="utf-8")
    order = [html.index(f'data-page="{n}"') for n in (1, 2, 100, 101, 1000)]
    assert order == sorted(order)


if __name__ == "__main__":
    test_merge_orders_pages_numerically()
    print("ok")
