"""Modals rendered into sibling wrappers that have no height of their own.

Apps mark the app container ``aria-hidden`` while a modal takes over and render
the modal into a sibling wrapper. That wrapper holds only a fixed-position
overlay, so it measures zero-height and lands wherever the page flow ends —
often far below the fold. The walk used to prune it as off-screen, and with the
``aria-hidden`` background already dropped the page came back empty.

The walk now judges every element on its own rect instead of pruning subtrees,
so the modal is reached through its collapsed wrapper. These pin that: the modal
is returned, and the inert background stays dropped.
"""

from __future__ import annotations

from tools.browser import browse_page

from .._helpers import find_ref


async def test_drawer_below_fold_kept_background_dropped(open_tab, servers):
    # Target's add-to-cart drawer and Airbnb's welcome modal: aria-hidden app
    # container, modal in a zero-height sibling wrapper past the end of a tall
    # page. Both sites returned no elements at all.
    tab = await open_tab(f"{servers.primary}/aria-hidden/app-hidden-drawer-below-fold.html")
    view = await browse_page(tab=tab)

    assert find_ref(view, role="button", name="View cart") is not None
    assert find_ref(view, role="button", name="Continue shopping") is not None
    assert find_ref(view, role="button", name="Add to cart") is None
    assert find_ref(view, role="link", name="Home") is None


async def test_portal_dialog_in_zero_height_root(open_tab, servers):
    # GitHub Docs' search overlay: the dialog is rendered into a height-0 portal
    # root as position:fixed, so the root measures as off-screen at the very top
    # of the page. The dialog's input and buttons must survive while its
    # aria-modal background is unavailable.
    tab = await open_tab(f"{servers.primary}/aria-hidden/portal-dialog.html")
    view = await browse_page(tab=tab)

    assert find_ref(view, role="searchbox", name="Search docs") is not None
    assert find_ref(view, role="button", name="Close") is not None
    assert find_ref(view, role="button", name="Open menu") is None
