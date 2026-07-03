"""Control states and less-common input types/names."""

from __future__ import annotations

from tools.browser.snapshot_tool import browse_page

from .._helpers import find_ref


async def test_states_and_types(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/control-states/page.html")
    view = await browse_page(tab=tab)

    # aria/native state annotations
    assert "Checked radio (checked)" in view
    assert "Selected tab (selected)" in view          # aria-selected
    # type="tel" maps to textbox
    assert find_ref(view, role="textbox", name="Phone") is not None
    # a labelless input falls back to its value attribute for the name
    assert find_ref(view, role="textbox", name="prefilled value") is not None
