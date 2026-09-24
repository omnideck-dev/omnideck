"""<details>/<summary> disclosure widgets can be expanded.

A closed <details> hides its body, so the agent must be able to open it. The
<summary> is surfaced as an interactive button (annotated collapsed), and
clicking it expands the details so the previously hidden body becomes reachable.
"""

from __future__ import annotations

from tools.browser import click
from tools.browser import browse_page

from .._helpers import find_ref


async def test_closed_summary_is_interactive_and_collapsed(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/disclosure/page.html")
    view = await browse_page(tab=tab)

    # The summary is a clickable button, marked collapsed; the body is hidden.
    assert find_ref(view, role="button", name="Expandable summary") is not None
    assert "(collapsed)" in view
    assert "Hidden body text" not in view


async def test_clicking_summary_expands_body(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/disclosure/page.html")
    view = await browse_page(tab=tab)

    ref = find_ref(view, role="button", name="Expandable summary")
    assert ref is not None
    await click(ref, tab=tab)

    after = await browse_page(tab=tab)
    # The details is now open: its body is reachable and the toggle reads expanded.
    assert "Hidden body text" in after
    assert "(expanded)" in after
