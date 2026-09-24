"""Interactive elements nested inside headings (h1-h6).

The walker emitted a heading and returned without descending, so a link that is a
heading's title (GitHub search, Wired) or a button wrapped in a heading
(theuselessweb) was never assigned a ref and could not be clicked. Headings now
follow the same rule as paragraph-like blocks: hold something interactive and the
walk descends into it, hold nothing interactive and the block is emitted whole.

This asserts the entire rendered view, so the text the agent actually reads is
right here rather than inferred from a substring match.
"""

from __future__ import annotations

from textwrap import dedent

from tools.browser import browse_page

from .._helpers import page_body


async def test_heading_links_view(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/heading-links/page.html")
    view = await browse_page(tab=tab)

    # What each line pins:
    #   1. An <h3> whose title is a link: the link carries the ref. The heading
    #      used to print its text and then print the link again, so the agent saw
    #      "omnideck-dev/omnideck" twice and could click neither copy.
    #   2. A <button> wrapped in an <h5> now gets a ref.
    #   3-4. A heading mixing text and a link keeps the text once and refs the link.
    #   5. A heading with nothing interactive inside is untouched and keeps its
    #      [h1] label.
    assert page_body(view) == dedent("""\
        [1] [link] omnideck-dev/omnideck
        [2] [button] PLEASE
        Latest:
        [3] [link] How Jay-Z pulled it off
        [h1] Just a headline
        Some body text so the page isn't heading-only.""")
