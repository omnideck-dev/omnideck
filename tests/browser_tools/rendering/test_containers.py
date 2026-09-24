"""Structural containers surface their content.

fieldset/legend, ordered lists, and definition lists render their text (and any
interactive children) rather than being dropped.
"""

from __future__ import annotations

from tools.browser import browse_page

from .._helpers import page_body


async def test_fieldset_ol_dl_render(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/containers/page.html")
    view = await browse_page(tab=tab)

    assert view.startswith(
        f"[Page: Containers | {servers.primary}/containers/page.html |  | tab=1]\n"
        "[Viewport: 0-"
    )
    # The browser chrome changes the exact viewport height between headed and
    # headless runs. The rendered document body should remain exact.
    assert page_body(view) == (
        "[h1] Containers\n"
        "Group legend\n"
        "[1] [textbox] Grouped input\n"
        "Ordered one\n"
        "Ordered two\n"
        "A term\n"
        "A definition"
    )
