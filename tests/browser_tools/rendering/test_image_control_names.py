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


async def test_image_alt_names_ignore_hidden_and_empty_alt_images(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/accessible-names/image-controls.html")
    view = await browse_page(full_page=True, tab=tab)

    assert find_ref(view, role="link", name="Visible destination") is not None
    assert "decoy" not in view


async def test_multiple_image_alt_names_follow_document_order(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/accessible-names/image-controls.html")
    view = await browse_page(full_page=True, tab=tab)

    assert find_ref(view, role="link", name="North South") is not None


async def test_tooltip_precedes_image_filename_fallback(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/accessible-names/image-controls.html")
    view = await browse_page(full_page=True, tab=tab)

    assert find_ref(view, role="link", name="Fallback title") is not None


async def test_image_names_preserve_explicit_and_text_labels(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/accessible-names/image-controls.html")
    view = await browse_page(full_page=True, tab=tab)

    for name in ("Explicit destination", "Referenced destination", "Text destination", "Image before tooltip"):
        assert find_ref(view, role="link", name=name) is not None
    assert "Ignored" not in view
    assert "Lower priority tooltip" not in view


@pytest.mark.parametrize(
    ("role", "filename", "result"),
    [("link", "contact-us.svg", "Filename link activated"), ("button", "a81f09cd.svg", "Filename button activated")],
)
async def test_unnamed_image_controls_use_literal_filenames(open_tab, servers, role, filename, result):
    tab = await open_tab(f"{servers.primary}/accessible-names/image-controls.html")
    view = await browse_page(tab=tab)

    ref = find_ref(view, role=role, name=filename)
    assert ref is not None
    assert f"[{ref}] [{role}] Unnamed image {role} (file: {filename})" in view.splitlines()
    assert "?size=large" not in view
    assert "#icon" not in view
    assert result in await click(ref, tab=tab)
