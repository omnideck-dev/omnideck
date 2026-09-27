"""Image-only controls retain names and usable refs in the rendered document."""

from __future__ import annotations

import pytest

from tools.browser import browse_page, click

from .._helpers import find_ref


@pytest.mark.parametrize(
    ("role", "name", "result"),
    [("link", "Image destination", "Link activated"), ("button", "Image action", "Button activated")],
)
async def test_image_only_controls_are_named_and_clickable(open_tab, servers, role, name, result):
    tab = await open_tab(f"{servers.primary}/accessible-names/image-controls.html")
    view = await browse_page(tab=tab)

    ref = find_ref(view, role=role, name=name)
    assert ref is not None
    assert result in await click(ref, tab=tab)


async def test_image_names_skip_hidden_and_decorative_images(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/accessible-names/image-controls.html")
    view = await browse_page(full_page=True, tab=tab)

    assert find_ref(view, role="link", name="Visible destination") is not None
    assert find_ref(view, role="link", name="North South") is not None
    assert find_ref(view, role="link", name="Fallback title") is not None
    assert "decoy" not in view


async def test_image_names_preserve_explicit_and_text_labels(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/accessible-names/image-controls.html")
    view = await browse_page(full_page=True, tab=tab)

    for name in ("Explicit destination", "Referenced destination", "Text destination", "Image before tooltip"):
        assert find_ref(view, role="link", name=name) is not None
    assert "Ignored" not in view
    assert "Lower priority tooltip" not in view
