"""Structural containers surface their content.

fieldset/legend, ordered lists, and definition lists render their text (and any
interactive children) rather than being dropped.
"""

from __future__ import annotations

from tools.browser.snapshot_tool import browse_page


async def test_fieldset_ol_dl_render(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/containers/page.html")
    view = await browse_page(tab=tab)

    # Assert the whole view verbatim (only the port in the URL is dynamic) so the
    # exact shape the LLM sees is visible here: legend/list/definition text is
    # surfaced inline and the grouped input is the sole ref'd control.
    assert view == (
        f"[Page: Containers | {servers.primary}/containers/page.html |  | tab=1]\n"
        "[Viewport: 0-993 of 993px]\n"
        "\n"
        "[h1] Containers\n"
        "Group legend\n"
        "[1] [textbox] Grouped input\n"
        "Ordered one\n"
        "Ordered two\n"
        "A term\n"
        "A definition"
    )
