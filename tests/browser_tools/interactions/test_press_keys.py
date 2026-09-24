"""press_keys sends key presses to the focused element (e.g. Enter submits)."""

from __future__ import annotations

from tools.browser import fill_field, press_keys
from tools.browser import browse_page

from .._helpers import find_ref


async def test_press_enter_submits_form(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/enter-submit/page.html")
    view = await browse_page(tab=tab)

    q = find_ref(view, role="textbox", name="Query")
    assert q is not None
    await fill_field(q, "hello", tab=tab)

    result = await press_keys(["Enter"], tab=tab)
    assert "Submitted: hello" in result
