"""Rendering failures remain actionable through the public browser tools."""

from __future__ import annotations

from tools.browser import browse_page, read_page


async def test_render_error_returns_fallback(open_tab, servers):
    """A DOM evaluation error explains the failure and offers recovery."""
    tab = await open_tab(f"{servers.primary}/snapshot-error/page.html")

    rendered = await browse_page(tab=tab)

    assert "Page content unavailable" in rendered
    assert "document rendering failed" in rendered
    assert "browse_page()" in rendered
    assert "read_page()" in rendered
    assert "Readable fallback content" in await read_page(tab=tab)
