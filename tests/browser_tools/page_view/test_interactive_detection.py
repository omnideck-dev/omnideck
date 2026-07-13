"""What counts as an interactive descendant.

The walk collapses a block into one node unless it holds something the agent can
act on, in which case it descends so the control gets a ref. That "something
interactive" test was written several times over: some copies matched a bare
``[role]`` selector, which counts non-interactive roles like ``note`` and shreds
ordinary prose; others matched no roles at all, which misses aria controls and
lets a tabbable wrapper swallow them into a single unusable ref.
"""

from __future__ import annotations

from tools.browser.snapshot_tool import browse_page

from .._helpers import find_ref

_FIXTURE = "interactive-detection/page.html"


async def test_non_interactive_role_does_not_split_prose(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/{_FIXTURE}")
    view = await browse_page(tab=tab)

    # A role="note" span is not actionable, so the sentence stays whole rather
    # than being broken into "Plain text with a" / "noted phrase" / "inside it.".
    assert "Plain text with a noted phrase inside it." in view
    assert "Inline start and a noted bit and the end." in view


async def test_real_link_in_paragraph_still_gets_a_ref(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/{_FIXTURE}")
    view = await browse_page(tab=tab)

    assert find_ref(view, role="link", name="the docs") is not None


async def test_wrapper_does_not_swallow_aria_controls(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/{_FIXTURE}")
    view = await browse_page(tab=tab)

    alpha = find_ref(view, role="button", name="Alpha")
    beta = find_ref(view, role="button", name="Beta")
    assert alpha is not None
    assert beta is not None
    # The wrapper used to take the only ref, named "Alpha Beta", leaving neither
    # button clickable. Both names then resolve to that same ref.
    assert alpha != beta


async def test_wrapper_does_not_swallow_native_controls(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/{_FIXTURE}")
    view = await browse_page(tab=tab)

    gamma = find_ref(view, role="button", name="Gamma")
    delta = find_ref(view, role="button", name="Delta")
    assert gamma is not None
    assert delta is not None
    assert gamma != delta
