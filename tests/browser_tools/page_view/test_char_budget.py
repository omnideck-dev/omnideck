"""browse_page enforces an 8000-char budget and flags truncation."""

from __future__ import annotations

from tools.browser.snapshot_tool import browse_page


async def test_char_budget_truncates(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/char-budget/page.html")
    view = await browse_page(full_page=True, tab=tab)

    # The 500-button page blows past the budget: the output is capped and
    # flagged truncated (the viewport line ends "px | truncated]"), and the
    # later buttons are dropped.
    assert "truncated" in view
    assert "Button 500" not in view
    assert len(view) < 9000
