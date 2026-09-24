"""browse_page reaches content nested inside zero-height wrapper chains.

Regression for SPA shells (e.g. Figma signup, Quora login) that render the real
content out of normal flow inside a height-0 wrapper. The wrapper contributes no
scrollHeight, so the viewport walk used to classify it as off-screen and stop
before reaching any of the interactive elements, leaving browse_page empty.
"""

from __future__ import annotations

from tools.browser import browse_page

from .._helpers import find_ref


async def test_absolute_content_under_zero_height_chain(open_tab, servers):
    # Content is position:absolute inside a two-level height-0 chain (Quora).
    tab = await open_tab(
        f"{servers.primary}/zero-height/absolute-content.html"
    )
    view = await browse_page(tab=tab)

    assert find_ref(view, role="link", name="Home") is not None
    assert find_ref(view, role="textbox", name="Email address") is not None
    assert find_ref(view, role="textbox", name="Password") is not None
    assert find_ref(view, role="button", name="Log in") is not None
    assert find_ref(view, role="button", name="Sign up") is not None


async def test_fixed_content_under_collapsed_wrapper(open_tab, servers):
    # A single height-0 full-width wrapper holds position:fixed content (Figma).
    tab = await open_tab(
        f"{servers.primary}/zero-height/collapsed-wrapper.html"
    )
    view = await browse_page(tab=tab)

    assert find_ref(view, role="link", name="Logo") is not None
    assert find_ref(view, role="button", name="Continue with Google") is not None
    assert find_ref(view, role="textbox", name="Work email") is not None
    assert find_ref(view, role="button", name="Continue with email") is not None
