"""Interactive elements nested inside headings (h1-h6) get their own ref.

The walker emitted a heading and returned without descending, so a link that is a
heading's title (GitHub search, Wired) or a button wrapped in a heading
(theuselessweb) was never assigned a ref and could not be clicked. Headings now
descend when they hold interactive content, while still emitting the heading for
structure.
"""

from __future__ import annotations

from tools.browser.snapshot_tool import browse_page

from .._helpers import find_ref


async def test_interactive_inside_headings_get_refs(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/heading-links/page.html")
    view = await browse_page(tab=tab)

    # <h3><a>…</a></h3>: the title link (GitHub search results, Wired headlines).
    assert find_ref(view, role="link", name="omnideck-dev/omnideck") is not None
    # <h5><button>PLEASE</button></h5> (theuselessweb).
    assert find_ref(view, role="button", name="PLEASE") is not None
    # A link inside a heading that also has plain text around it.
    assert find_ref(view, role="link", name="How Jay-Z pulled it off") is not None


async def test_plain_heading_unchanged(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/heading-links/page.html")
    view = await browse_page(tab=tab)

    # A heading with no interactive child still shows as text and gets no ref.
    assert "Just a headline" in view
    assert find_ref(view, name="Just a headline") is None
