"""Modal dialog: the aria-hidden background is dropped, the dialog is kept.

When a modal opens, apps mark the rest of the page ``aria-hidden`` and render
the dialog as a sibling. The walker skips an aria-hidden subtree — *unless* it
contains a dialog — so the background controls vanish while the sibling
``role="dialog"`` is walked normally. Without that carve-out the agent could
neither see the background (correct) nor the modal (wrong).
"""

from __future__ import annotations

from tools.browser.snapshot_tool import browse_page

from .._helpers import find_ref


async def test_modal_shown_background_hidden(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/modal-dialog/page.html")
    view = await browse_page(full_page=True, tab=tab)

    # Background button is under aria-hidden -> dropped; the sibling dialog is
    # walked, so its button survives.
    assert find_ref(view, role="button", name="Modal button") is not None
    assert find_ref(view, role="button", name="Background button") is None
