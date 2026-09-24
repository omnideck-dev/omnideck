"""read_page returns the whole page as markdown, navigable by chunk and query."""

from __future__ import annotations

import pytest

from tools.browser import BrowserToolError
from tools.browser import read_page

_EXPECTED_MARKDOWN = """\
# The Hubble Telescope

Hubble has orbited Earth since 1990, returning deep-field images of distant galaxies.

## Instruments

It carries cameras and spectrographs. See the [mission overview](</article/article.html>) for details.

  * Wide Field Camera 3
  * Cosmic Origins Spectrograph"""


def _split(text: str) -> tuple[str, str, str]:
    """Split a read_page result into (header block, status line(s), markdown)."""
    header, _, rest = text.partition("\n\n")
    status, _, body = rest.partition("\n\n")
    return header, status, body


async def test_read_page_returns_markdown(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/article/article.html")
    text = await read_page(tab=tab)

    # Output is "[Page: ...]\n\n[chunk ...]\n\n<markdown>". The header's URL port
    # is runtime-dependent; the rest is exact.
    header, status, body = _split(text)
    assert (
        f"[Page: The Hubble Telescope | {servers.primary}/article/article.html"
        in header
    )
    # No viewport line and no empty status slot on a read.
    assert "Viewport:" not in text
    assert header.endswith("]")
    assert " |  |" not in header
    # A page that fits in one chunk says so and offers no next chunk.
    assert status == f"[chunk 1/1 · {len(_EXPECTED_MARKDOWN):,} chars total]"
    assert body == _EXPECTED_MARKDOWN


async def test_read_page_returns_whole_page_not_the_article(open_tab, servers):
    # Regression for pages like noaa.gov: an <article> wraps only the lead
    # headline, sitting beside the <main> that holds the real content. Reading
    # the whole page returns both, so no selector can strand the agent on the
    # headline alone.
    tab = await open_tab(f"{servers.primary}/thin-article/thin-article.html")
    _, _, body = _split(await read_page(tab=tab))

    assert "Storm warning issued for the eastern seaboard" in body
    assert "Latest forecasts" in body
    assert "tropical storm forecasts" in body
    assert "Northeast River Forecast Center" in body
    assert "Contact the newsroom" in body


async def test_read_page_returns_all_reviews_not_the_first(open_tab, servers):
    # Regression for pages like letterboxd.com: the first <article> wraps a
    # single review nested inside a large <main>. Reading the whole page returns
    # the synopsis, the credits, and every review, each exactly once.
    tab = await open_tab(f"{servers.primary}/thin-article/nested-review.html")
    _, _, body = _split(await read_page(tab=tab))

    assert "Thirty years after the events" in body
    assert "Directed by Denis Villeneuve" in body
    assert "Review by neon_dreams" in body
    assert "Review by late_night_screening" in body
    assert body.count("Review by cinephile_42") == 1


async def test_read_page_chunks_reassemble(open_tab, servers, monkeypatch):
    # Shrink the read budget so the small article spans several chunks, letting
    # us exercise the chunking without a huge fixture.
    monkeypatch.setattr("tools.browser.read._READ_BUDGET", 100)

    tab = await open_tab(f"{servers.primary}/article/article.html")

    bodies: list[str] = []
    chunk = 1
    while True:
        _, status, body = _split(await read_page(chunk=chunk, tab=tab))
        bodies.append(body)
        assert status.startswith(f"[chunk {chunk}/")
        # A non-final chunk points at the next one; the last one doesn't.
        if f"Read on with chunk={chunk + 1}" not in status:
            break
        assert len(body) <= 100
        chunk += 1

    # The content spanned more than one chunk, and the chunks reconstruct the
    # whole markdown in order with no overlap or gap.
    assert chunk > 1
    assert "".join(bodies) == _EXPECTED_MARKDOWN

    # The final chunk stops offering a next one.
    assert "Read on with chunk=" not in status

    # Reading past the last chunk is an error, not an empty result.
    with pytest.raises(BrowserToolError, match="past the end"):
        await read_page(chunk=chunk + 1, tab=tab)


async def test_read_page_chunk_boundary_lands_on_a_line(
    open_tab, servers, monkeypatch
):
    # A chunk ends at a line break rather than mid-word whenever the line fits
    # the budget, so a paragraph is not sliced in half.
    monkeypatch.setattr("tools.browser.read._READ_BUDGET", 120)

    tab = await open_tab(f"{servers.primary}/article/article.html")
    _, _, first = _split(await read_page(chunk=1, tab=tab))

    assert first.startswith("# The Hubble Telescope")
    assert first.endswith("\n")


async def test_read_page_chunk_zero_raises(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/article/article.html")

    with pytest.raises(BrowserToolError, match="chunk must be 1"):
        await read_page(chunk=0, tab=tab)


async def test_read_page_status_line_signals_more_chunks(
    open_tab, servers, monkeypatch
):
    # The "more remains" cue lives on the chunk status line, not a viewport
    # line. A non-final chunk names the next one; the final chunk doesn't.
    monkeypatch.setattr("tools.browser.read._READ_BUDGET", 100)

    tab = await open_tab(f"{servers.primary}/article/article.html")

    # At a 100-char budget the 286-char article spans five chunks.
    _, first_status, _ = _split(await read_page(tab=tab))
    _, last_status, _ = _split(await read_page(chunk=5, tab=tab))

    assert first_status.startswith("[chunk 1/5 ·")
    assert "Read on with chunk=2" in first_status
    assert last_status.startswith("[chunk 5/5 ·")
    assert "Read on with chunk=" not in last_status


async def test_read_page_query_locates_matches_by_chunk(
    open_tab, servers, monkeypatch
):
    # Query searches the whole page, not just one chunk, and tells the agent
    # which chunk the match sits in so it can go read around it. Here the two
    # occurrences are close enough to merge into a single passage, and chunk 4
    # is the one that opens on the matching paragraph.
    monkeypatch.setattr("tools.browser.read._READ_BUDGET", 100)

    tab = await open_tab(f"{servers.primary}/article/article.html")
    _, _, rest = (await read_page(query="spectrograph", tab=tab)).partition("\n\n")

    assert '[Search "spectrograph" — 1 match(es) in chunk 4 of 5.]' in rest
    assert "\n---\n" not in rest
    assert rest.rstrip().endswith("(chunk 4)")
    assert "Cosmic Origins Spectrograph" in rest
    # A real paragraph of context either side comes along with the match.
    assert "## Instruments" in rest
    assert "Wide Field Camera 3" in rest


async def test_read_page_query_context_is_not_a_blank_line(
    open_tab, servers
):
    # Markdown separates blocks with blank lines. Context is counted in
    # non-blank lines, so a match arrives with real surrounding prose rather
    # than the blank separator that follows every block.
    tab = await open_tab(f"{servers.primary}/article/article.html")
    _, _, rest = (await read_page(query="orbited", tab=tab)).partition("\n\n")

    assert "Hubble has orbited Earth" in rest
    assert "# The Hubble Telescope" in rest
    assert "## Instruments" in rest


async def test_read_page_query_no_matches(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/article/article.html")
    text = await read_page(query="quasar", tab=tab)

    assert '[Search "quasar" — no matches on this page' in text
    assert "1 chunks" in text
