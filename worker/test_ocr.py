"""Run: python worker/test_ocr.py"""
import os

os.environ.setdefault("JOBS_DIR", "/tmp/jobs")

from worker.ocr import _page_outputs


def test_page_outputs():
    txt, html = _page_outputs("line one\n\n  \n<b>two</b> & \"three\"\n", 7)

    assert txt == 'line one\n<b>two</b> & "three"'
    assert html == (
        '<div class="page" data-page="7">\n'
        "  <p>line one</p>\n"
        "  <p>&lt;b&gt;two&lt;/b&gt; &amp; &quot;three&quot;</p>\n"
        "</div>"
    )

    # empty page → empty div, no stray <p>
    txt, html = _page_outputs("", 1)
    assert txt == ""
    assert html == '<div class="page" data-page="1">\n\n</div>'


if __name__ == "__main__":
    test_page_outputs()
    print("ok")
