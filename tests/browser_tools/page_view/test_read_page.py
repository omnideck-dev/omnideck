"""read_page returns clean markdown (headings, lists, links) for a content page."""

from __future__ import annotations

import pytest

from tools.browser.core.exceptions import BrowserToolError
from tools.browser.read_content import read_page

_EXPECTED_MARKDOWN = """\
# The Hubble Telescope

Hubble has orbited Earth since 1990, returning deep-field images of distant galaxies.

## Instruments

It carries cameras and spectrographs. See the
[mission overview](/article/article.html) for details.

- Wide Field Camera 3
- Cosmic Origins Spectrograph"""


async def test_read_page_returns_markdown(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/article/article.html")
    text = await read_page(tab=tab)

    # Output is "[Page: ...]\n[Viewport: ...]\n\n<markdown>". The header's URL
    # port and viewport size are runtime-dependent; the markdown body is exact.
    header, _, body = text.partition("\n\n")
    assert (
        f"[Page: The Hubble Telescope | {servers.primary}/article/article.html"
        in header
    )
    assert body.strip() == _EXPECTED_MARKDOWN


async def test_read_page_thin_article_beside_main(browser_session, servers):
    # Regression for pages like noaa.gov: an <article> wraps only the lead
    # headline, sitting beside the <main> that holds the real content. The old
    # selector returned the <article> and produced a single line. Preferring
    # <main> gives the agent the actual page content.
    tab = await browser_session.open(f"{servers.primary}/thin-article/thin-article.html")
    _, _, body = (await read_page(tab=tab)).partition("\n\n")

    # The <main> content is present — we didn't stop at the thin article.
    assert "Latest forecasts" in body
    assert "tropical storm forecasts" in body
    assert "Northeast River Forecast Center" in body
    assert "Contact the newsroom" in body


async def test_read_page_thin_article_inside_main(browser_session, servers):
    # Regression for pages like letterboxd.com: the first <article> wraps a
    # single review nested inside a large <main>. The old selector returned that
    # one review and dropped the rest of the page. Preferring <main> returns the
    # whole page, and since the review lives inside <main> it still appears,
    # exactly once, rather than being returned alone.
    tab = await browser_session.open(f"{servers.primary}/thin-article/nested-review.html")
    _, _, body = (await read_page(tab=tab)).partition("\n\n")

    # The bulk of <main> is present — synopsis, credits, and the other reviews.
    assert "Thirty years after the events" in body
    assert "Directed by Denis Villeneuve" in body
    assert "Review by neon_dreams" in body
    assert "Review by late_night_screening" in body
    # The nested review is still there, exactly once.
    assert body.count("Review by cinephile_42") == 1


async def test_read_page_paginates(browser_session, servers, monkeypatch):
    # Shrink the read budget so the small article spans several pages, letting
    # us exercise the slice/truncate/past-end logic without a huge fixture.
    monkeypatch.setattr("tools.browser.read_content._READ_BUDGET", 100)

    tab = await browser_session.open(f"{servers.primary}/article/article.html")

    # Walk pages until one comes back not truncated, collecting each body.
    bodies: list[str] = []
    page_number = 1
    while True:
        header, _, body = (await read_page(page_number=page_number, tab=tab)).partition("\n\n")
        bodies.append(body)
        if "truncated" not in header:
            break
        # Every non-final page fills the budget exactly.
        assert len(body) == 100
        page_number += 1

    # The content actually spanned more than one page, and the pages
    # reconstruct the whole markdown in order with no overlap or gap.
    assert page_number > 1
    assert "".join(bodies).strip() == _EXPECTED_MARKDOWN

    # Reading past the last page is an error, not an empty result.
    with pytest.raises(BrowserToolError):
        await read_page(page_number=page_number + 1, tab=tab)


async def test_read_page_viewport_reports_truncation(browser_session, servers, monkeypatch):
    # The truncation marker lives on the "[Viewport: ...]" line — it's the
    # agent's cue to fetch the next page — so pin its exact shape.
    monkeypatch.setattr("tools.browser.read_content._READ_BUDGET", 100)

    tab = await browser_session.open(f"{servers.primary}/article/article.html")

    # Line 0 is "[Page: ...]", line 1 is "[Viewport: ...]". At 100-char pages
    # the ~280-char article truncates on page 1 and ends on page 3.
    truncated_viewport = (await read_page(tab=tab)).splitlines()[1]
    final_viewport = (await read_page(page_number=3, tab=tab)).splitlines()[1]

    assert truncated_viewport.startswith("[Viewport: 0-")
    assert truncated_viewport.endswith("px | truncated]")
    assert final_viewport.endswith("px]")
    assert "truncated" not in final_viewport
