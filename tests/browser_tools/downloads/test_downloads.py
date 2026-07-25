"""Downloads: clicking a file link returns a File Download view and saves it.

Covers an explicit same-origin PDF download link, a Content-Disposition
attachment, and direct navigation to a file content type.
"""

from __future__ import annotations

from tools.browser import browse_page, click, goto

from .._helpers import find_ref


async def test_pdf_link_triggers_download(open_tab, downloads_dir, servers):
    tab = await open_tab(f"{servers.primary}/downloads/links.html")
    view = await browse_page(tab=tab)

    ref = find_ref(view, role="link", name="Download the PDF")
    assert ref is not None
    result = await click(ref, tab=tab)

    # The tool reports a file download rather than a page snapshot...
    assert "Download" in result
    # ...and a PDF landed on disk in the downloads dir.
    pdfs = list(downloads_dir.glob("*.pdf"))
    assert pdfs, f"no pdf in {downloads_dir}: {list(downloads_dir.iterdir())}"
    assert pdfs[0].read_bytes().startswith(b"%PDF")


async def test_attachment_link_triggers_download(open_tab, downloads_dir, servers):
    tab = await open_tab(f"{servers.primary}/downloads/links.html")
    view = await browse_page(tab=tab)

    ref = find_ref(view, role="link", name="Download the file")
    assert ref is not None
    result = await click(ref, tab=tab)

    assert "Download" in result
    saved = downloads_dir / "report.bin"
    assert saved.exists(), f"report.bin not in {downloads_dir}: {list(downloads_dir.iterdir())}"
    assert saved.stat().st_size == 4096


async def test_goto_pdf_returns_download(open_tab, downloads_dir, servers):
    """Direct file navigation covers Chromium's aborted-navigation download path."""
    tab = await open_tab(f"{servers.primary}/downloads/links.html")

    result = await goto(f"{servers.primary}/downloads/doc.pdf", tab=tab)

    assert "Download" in result
    pdfs = list(downloads_dir.glob("*.pdf"))
    assert pdfs, f"no pdf in {downloads_dir}: {list(downloads_dir.iterdir())}"
    assert pdfs[0].read_bytes().startswith(b"%PDF")
