"""browse_page enforces an 8000-char budget and flags truncation."""

from __future__ import annotations

from tools.browser import browse_page


async def test_char_budget_truncates(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/char-budget/page.html")
    view = await browse_page(full_page=True, tab=tab)

    # The 500-button page blows past the budget: the output is capped and
    # flagged truncated (the viewport line ends "px | truncated]"), and the
    # later buttons are dropped.
    assert "truncated" in view
    assert "Button 500" not in view
    assert len(view) < 9000
