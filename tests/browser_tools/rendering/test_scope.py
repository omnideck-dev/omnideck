"""browse_page(scope=...) narrows the view to a section by heading.

scope finds a heading whose text contains the query (exact match preferred,
then substring) and keeps just that section — the heading down to the next
heading of the same or higher level. If nothing matches, it falls back to the
full page with a "[scope ... not found ...]" marker rather than an empty view.
"""

from __future__ import annotations

from tools.browser import browse_page

from .._helpers import find_ref


async def test_scope_narrows_to_section(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/scope/page.html")
    view = await browse_page(scope="Section B", tab=tab)

    # Only Section B's control survives — not Alpha (earlier section) or
    # Charlie (the next section, which ends the scope).
    assert find_ref(view, role="button", name="Bravo button") is not None
    assert find_ref(view, role="button", name="Alpha button") is None
    assert find_ref(view, role="button", name="Charlie button") is None


async def test_scope_not_found_shows_full_page(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/scope/page.html")
    view = await browse_page(scope="Nonexistent", tab=tab)

    # No matching heading -> full page, flagged, so the agent isn't left blind.
    assert "not found, showing full page" in view
    assert find_ref(view, role="button", name="Alpha button") is not None
    assert find_ref(view, role="button", name="Charlie button") is not None
