"""Snapshot failures remain actionable through the public browser tools."""

from __future__ import annotations

from tools.browser import browse_page, read_page


async def test_snapshot_error_returns_fallback(browser_session, servers):
    """A walker evaluation error explains the failure and offers recovery."""
    tab = await browser_session.open(f"{servers.primary}/snapshot-error/page.html")

    view = await browse_page(tab=tab)

    assert "Page content unavailable" in view
    assert "snapshot failed" in view
    assert "browse_page()" in view
    assert "read_page()" in view
    assert "Readable fallback content" in await read_page(tab=tab)
