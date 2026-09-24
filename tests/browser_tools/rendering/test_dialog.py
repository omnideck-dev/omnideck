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


async def test_full_viewport_aria_takeover_is_active_surface(open_tab, servers):
    """A covered background is unavailable even when the document can scroll."""
    tab = await open_tab(f"{servers.primary}/modal-dialog/aria-nonblocking.html?layout=takeover")
    view = await browse_page(tab=tab)

    assert "[Modal dialog open" in view
    assert find_ref(view, role="button", name="Background action") is None
    accept_ref = find_ref(view, role="button", name="Accept and continue")
    assert accept_ref is not None

    after_accept = await click(accept_ref, tab=tab)
    assert "[Modal dialog open" not in after_accept
    assert find_ref(after_accept, role="button", name="Background action") is not None


async def test_aria_hidden_background_defines_active_surface(open_tab, servers):
    """An aria-hidden, pointer-disabled app leaves its sibling dialog active."""
    tab = await open_tab(f"{servers.primary}/modal-dialog/aria-hidden-background.html")
    view = await browse_page(tab=tab)

    assert "[Modal dialog open" in view
    assert find_ref(view, role="button", name="Background action") is None
    continue_ref = find_ref(view, role="button", name="Continue")
    assert continue_ref is not None

    after_continue = await click(continue_ref, tab=tab)
    assert "[Modal dialog open" not in after_continue
    assert find_ref(after_continue, role="button", name="Background action") is not None


async def test_focus_trapped_aria_surface_hides_background(open_tab, servers):
    """A focus trap and pointer-blocking layer define one active surface."""
    tab = await open_tab(f"{servers.primary}/modal-dialog/focus-trap.html")
    view = await browse_page(tab=tab)

    assert "[Modal dialog open" in view
    assert find_ref(view, role="button", name="Background action") is None
    assert find_ref(view, role="textbox", name="Project name") is not None
    done_ref = find_ref(view, role="button", name="Done")
    assert done_ref is not None

    after_done = await click(done_ref, tab=tab)
    assert "[Modal dialog open" not in after_done
    assert find_ref(after_done, role="button", name="Background action") is not None


async def test_pointer_blocker_without_modal_semantics_hides_background(open_tab, servers):
    """Pointer interception matters even when the page supplies no modal metadata."""
    tab = await open_tab(f"{servers.primary}/modal-dialog/pointer-blocker.html")
    view = await browse_page(tab=tab)

    assert "[Modal dialog open" in view
    assert find_ref(view, role="button", name="Background action") is None
    continue_ref = find_ref(view, role="button", name="Continue to page")
    assert continue_ref is not None

    after_continue = await click(continue_ref, tab=tab)
    assert "[Modal dialog open" not in after_continue
    assert find_ref(after_continue, role="button", name="Background action") is not None


async def test_transparent_pointer_backdrop_hides_background(open_tab, servers):
    """Pointer interception remains real when the backdrop has no paint."""
    tab = await open_tab(f"{servers.primary}/modal-dialog/transparent-backdrop.html")
    view = await browse_page(tab=tab)

    assert "[Modal dialog open" in view
    assert find_ref(view, role="button", name="Background action") is None
    return_ref = find_ref(view, role="button", name="Return to report")
    assert return_ref is not None

    after_return = await click(return_ref, tab=tab)
    assert "[Modal dialog open" not in after_return
    assert find_ref(after_return, role="button", name="Background action") is not None


async def test_fixed_fullscreen_application_is_not_modal(open_tab, servers):
    """A fixed app root owns the page; it does not cover another interaction surface."""
    tab = await open_tab(f"{servers.primary}/modal-dialog/fixed-app-shell.html")
    view = await browse_page(tab=tab)

    assert "[Modal dialog open" not in view
    compose_ref = find_ref(view, role="button", name="Compose message")
    assert compose_ref is not None

    after_compose = await click(compose_ref, tab=tab)
    assert "Composer opened" in after_compose


async def test_nonblocking_aria_drawer_keeps_exposed_background(open_tab, servers):
    """A large drawer is not modal while the uncovered page remains actionable."""
    tab = await open_tab(f"{servers.primary}/modal-dialog/nonblocking-drawer.html")
    view = await browse_page(tab=tab)

    assert "[Modal dialog open" not in view
    assert find_ref(view, role="button", name="Apply filters") is not None
    background_ref = find_ref(view, role="button", name="Background action")
    assert background_ref is not None

    after_background = await click(background_ref, tab=tab)
    assert "Background activated" in after_background


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
