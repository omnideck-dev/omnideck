"""Modal surfaces expose only the controls the agent can currently use."""

from __future__ import annotations

from urllib.parse import urlencode

import pytest

from tools.browser import browse_page, click

from .._helpers import find_ref


async def test_modal_shown_background_hidden(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/modal-dialog/page.html")
    view = await browse_page(full_page=True, tab=tab)

    # Background button is under aria-hidden -> dropped; the sibling dialog is
    # walked, so its button survives.
    assert find_ref(view, role="button", name="Modal button") is not None
    assert find_ref(view, role="button", name="Background button") is None


async def test_native_modal_dialog_hides_inert_background(open_tab, servers):
    """A top-layer native dialog is the only available interaction surface."""
    tab = await open_tab(f"{servers.primary}/modal-dialog/native.html")
    view = await browse_page(tab=tab)

    assert find_ref(view, role="button", name="Background action") is None
    assert find_ref(view, role="button", name="Continue") is not None
    assert find_ref(view, role="button", name="Close") is not None
    assert "[Modal dialog open" in view


async def test_native_modal_inside_shadow_dom_hides_background(open_tab, servers):
    """Top-layer dialogs remain modal when hosted in an open shadow root."""
    tab = await open_tab(f"{servers.primary}/modal-dialog/shadow-native.html")
    view = await browse_page(tab=tab)

    assert "[Modal dialog open" in view
    assert find_ref(view, role="button", name="Background action") is None
    assert find_ref(view, role="button", name="Continue") is not None
    close_ref = find_ref(view, role="button", name="Close")
    assert close_ref is not None

    after_close = await click(close_ref, tab=tab)
    assert "[Modal dialog open" not in after_close
    assert find_ref(after_close, role="button", name="Background action") is not None


async def test_stacked_native_modals_show_top_layer_order(open_tab, servers):
    """The focused top-layer dialog wins even when DOM order says otherwise."""
    tab = await open_tab(f"{servers.primary}/modal-dialog/stacked-native.html")
    view = await browse_page(tab=tab)

    assert find_ref(view, role="button", name="Close underlying dialog") is None
    close_top = find_ref(view, role="button", name="Close top dialog")
    assert close_top is not None

    after_close = await click(close_top, tab=tab)
    assert "[Modal dialog open" in after_close
    assert find_ref(after_close, role="button", name="Close underlying dialog") is not None
    assert find_ref(after_close, role="button", name="Background action") is None


@pytest.mark.parametrize("role", ["dialog", "alertdialog"])
async def test_aria_modal_dialog_hides_unavailable_background(open_tab, servers, role):
    """ARIA dialog plus an inert background forms a modal interaction surface."""
    query = urlencode({"role": role})
    tab = await open_tab(f"{servers.primary}/modal-dialog/aria-modal.html?{query}")
    view = await browse_page(tab=tab)

    assert find_ref(view, role="button", name="Background action") is None
    assert find_ref(view, role="button", name="Acknowledge") is not None
    assert "[Modal dialog open — background controls are unavailable]" in view


async def test_unnamed_modal_close_button_is_actionable(open_tab, servers):
    """A modal close icon can use its implementation metadata as a fallback."""
    tab = await open_tab(f"{servers.primary}/modal-dialog/unnamed-close.html")
    view = await browse_page(tab=tab)
    close_ref = find_ref(view, role="button", name="Close")

    assert close_ref is not None
    after_close = await click(close_ref, tab=tab)
    assert "[Modal dialog open" not in after_close
    assert find_ref(after_close, role="button", name="Background action") is not None


async def test_cross_origin_custom_modal_surfaces_blocking_state_and_close(open_tab, servers):
    """A custom embedded modal keeps its root-document close action visible."""
    query = urlencode({"src": f"{servers.secondary}/modal-dialog/frame-content.html"})
    tab = await open_tab(f"{servers.primary}/modal-dialog/cross-frame.html?{query}")
    view = await browse_page(tab=tab)

    assert find_ref(view, role="button", name="Background action") is None
    close_ref = find_ref(view, role="button", name="Close")
    assert close_ref is not None
    assert "[Modal dialog open" in view

    after_close = await click(close_ref, tab=tab)
    assert "[Modal dialog open" not in after_close
    assert find_ref(after_close, role="button", name="Background action") is not None


async def test_custom_modal_with_sibling_panel_surfaces_panel_controls(open_tab, servers):
    """A backdrop and its separate dialog panel form one modal surface."""
    tab = await open_tab(f"{servers.primary}/modal-dialog/sibling-panel.html")
    view = await browse_page(tab=tab)

    assert "[Modal dialog open" in view
    assert find_ref(view, role="button", name="Background action") is None
    assert find_ref(view, role="button", name="Confirm") is not None
    close_ref = find_ref(view, role="button", name="Close")
    assert close_ref is not None

    after_close = await click(close_ref, tab=tab)
    assert "[Modal dialog open" not in after_close
    assert find_ref(after_close, role="button", name="Background action") is not None


async def test_modeless_open_dialog_keeps_background_available(open_tab, servers):
    """An open but modeless dialog does not make its background unavailable."""
    tab = await open_tab(f"{servers.primary}/modal-dialog/modeless.html")
    view = await browse_page(tab=tab)

    assert "[Modal dialog open" not in view
    assert find_ref(view, role="button", name="Dialog action") is not None
    assert find_ref(view, role="button", name="Background action") is not None
