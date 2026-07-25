"""What counts as an interactive descendant.

The walk collapses a block into one node unless it holds something the agent can
act on, in which case it descends so the control gets a ref. That "something
interactive" test was written several times over: some copies matched a bare
``[role]`` selector, which counts non-interactive roles like ``note`` and shreds
ordinary prose; others matched no roles at all, which misses aria controls and
lets a tabbable wrapper swallow them into a single unusable ref.

This asserts the whole rendered view, so the text the agent actually reads is
right here rather than inferred from a substring match.
"""

from __future__ import annotations

from textwrap import dedent

from tools.browser import browse_page

from .._helpers import page_body


async def test_interactive_detection_view(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/interactive-detection/page.html")
    view = await browse_page(tab=tab)

    # What each line pins:
    #   1. A role="note" span is not actionable, so the sentence stays whole. It
    #      came back as "Plain text with a" / "noted phrase" / "inside it." before.
    #   2-4. A real link is still descended into and keeps its own ref.
    #   5. An inline-only container holding a role="note" also stays one block.
    #   6-7. A tabbable wrapper no longer swallows its two aria buttons. They used
    #      to fuse into one ref named "Alpha Beta" that could click neither.
    #   8-9. The same wrapper around native buttons keeps working, as it already did.
    #   10. A named, non-native role="button" container steps aside for its real
    #       search input instead of dropping the entire subtree.
    assert page_body(view) == dedent("""\
        Plain text with a noted phrase inside it.
        Read
        [1] [link] the docs
        now.
        Inline start and a noted bit and the end.
        [2] [button] Alpha
        [3] [button] Beta
        [4] [button] Gamma
        [5] [button] Delta
        [6] [searchbox] Search docs""")
