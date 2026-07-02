"""Downloads: clicking a file link returns a File Download view and saves it.

Covers both download paths — a PDF (file content-type, handled via the
--disable-pdf-viewer download) and a Content-Disposition attachment.
"""

from __future__ import annotations

from pathlib import Path

from tools.browser.interactions import click
from tools.browser.snapshot_tool import browse_page

from .._helpers import find_ref


async def test_pdf_link_triggers_download(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/downloads/links.html")
    view = await browse_page(tab=tab)

    ref = find_ref(view, role="link", name="Download the PDF")
    assert ref is not None
    result = await click(ref, tab=tab)

    # The tool reports a file download rather than a page snapshot...
    assert "Download" in result
    # ...and a PDF landed on disk in the downloads dir.
    dl_dir = Path(browser_session.browser._downloads_dir)
    pdfs = list(dl_dir.glob("*.pdf"))
    assert pdfs, f"no pdf in {dl_dir}: {list(dl_dir.iterdir())}"
    assert pdfs[0].read_bytes().startswith(b"%PDF")


async def test_attachment_link_triggers_download(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/downloads/links.html")
    view = await browse_page(tab=tab)

    ref = find_ref(view, role="link", name="Download the file")
    assert ref is not None
    result = await click(ref, tab=tab)

    assert "Download" in result
    dl_dir = Path(browser_session.browser._downloads_dir)
    saved = dl_dir / "report.bin"
    assert saved.exists(), f"report.bin not in {dl_dir}: {list(dl_dir.iterdir())}"
    assert saved.stat().st_size == 4096
