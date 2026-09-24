"""Developer-visible cursor behavior in real headed Chrome."""

from __future__ import annotations

from tools.browser import browse_page, click, execute_javascript

from .._helpers import find_ref


async def test_click_keeps_cursor_overlay_in_document(open_tab, servers):
    """A public click leaves both cosmetic cursor elements available to captures."""
    tab_id = await open_tab(f"{servers.primary}/scope/page.html")
    rendered = await browse_page(tab=tab_id)
    ref = find_ref(rendered, role="button", name="Alpha button")
    assert ref is not None

    await click(ref, tab=tab_id)

    cursor_elements = await execute_javascript(
        """() => ({
            ring: !!document.getElementById('__llm_cursor_ring__'),
            dot: !!document.getElementById('__llm_cursor_dot__'),
        })""",
        tab=tab_id,
    )
    assert 'Result: {"ring": true, "dot": true}' in cursor_elements
