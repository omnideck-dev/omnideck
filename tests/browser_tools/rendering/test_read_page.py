"""read_page returns the whole page as markdown, navigable by chunk and query."""

from __future__ import annotations

import pytest

from config import load_config
from tools.browser import BrowserToolError, read_page, save_page_content
from tools.browser._tool_context import get_document

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
    assert f"[Page: The Hubble Telescope | {servers.primary}/article/article.html" in header
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


async def test_read_page_chunk_boundary_lands_on_a_line(open_tab, servers, monkeypatch):
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


async def test_read_page_status_line_signals_more_chunks(open_tab, servers, monkeypatch):
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


async def test_read_page_query_locates_matches_by_chunk(open_tab, servers, monkeypatch):
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


async def test_read_page_query_context_is_not_a_blank_line(open_tab, servers):
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


async def test_read_page_includes_nested_shadow_content_and_distributed_slots(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/shadow-content/page.html")
    _, _, body = _split(await read_page(tab=tab))

    assert "Privacy choices" in body
    assert "# Example Money Market Fund" in body
    assert "## Performance" in body
    assert "Seven-day yield: **3.63%**." in body
    assert "* NAV: $1.00" in body
    assert "[Prospectus](</documents/prospectus.pdf>)" in body
    for text in (
        "An investment profile rendered with web components.",
        "Slotted risk disclosure.",
        "Default disclosure.",
        "Default slot paragraph.",
        "Light DOM footer.",
    ):
        assert body.count(text) == 1
    assert "Unused" not in body
    assert "Unassigned light DOM content" not in body
    assert body.index("Privacy choices") < body.index("# Example") < body.index("## Performance")
    assert body.index("## Performance") < body.index("Default disclosure") < body.index("Light DOM footer")


async def test_shadow_content_can_be_searched_and_chunked(open_tab, servers, monkeypatch):
    tab = await open_tab(f"{servers.primary}/shadow-content/page.html")
    _, _, whole = _split(await read_page(tab=tab))
    monkeypatch.setattr("tools.browser.read._READ_BUDGET", 100)
    search = await read_page(query="Seven-day yield", tab=tab)
    assert "1 match(es)" in search
    assert "3.63%" in search

    parts = []
    for chunk in range(1, 20):
        _, status, body = _split(await read_page(chunk=chunk, tab=tab))
        parts.append(body)
        if "Read on with chunk=" not in status:
            break
    else:
        pytest.fail("Shadow content did not finish within the expected chunks")
    assert len(parts) > 1
    assert "".join(parts) == whole


async def test_shadow_content_read_does_not_mutate_page_or_construct_components(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/shadow-content/page.html")
    _, _, document = await get_document("read_page", tab=tab)
    before = await document.evaluate("""() => ({
        html: document.documentElement.outerHTML,
        constructions: window.componentConstructions,
        slots: document.querySelector('fund-overview').shadowRoot.querySelector('slot').assignedNodes().length,
    })""")
    first = await read_page(tab=tab)
    assert "Seven-day yield" in first
    assert await read_page(tab=tab) == first
    after = await document.evaluate("""() => ({
        html: document.documentElement.outerHTML,
        constructions: window.componentConstructions,
        slots: document.querySelector('fund-overview').shadowRoot.querySelector('slot').assignedNodes().length,
    })""")
    assert before == after
    assert after["constructions"] == 2


async def test_save_page_content_matches_shadow_dom_read(open_tab, servers, tmp_path, monkeypatch):
    config = load_config().model_copy(deep=True)
    config.virtual_computer.home_dir = str(tmp_path)
    monkeypatch.setattr("tools.browser.save.load_config", lambda: config)
    tab = await open_tab(f"{servers.primary}/shadow-content/page.html")
    _, _, body = _split(await read_page(tab=tab))
    await save_page_content("profile.md", tab=tab)
    saved = (tmp_path / "profile.md").read_text()
    assert "Seven-day yield" in saved
    assert saved.strip() == body


async def test_read_page_extracts_shadow_content_from_selected_cross_origin_frame(open_tab, servers):
    url = servers.embed(f"{servers.secondary}/shadow-content/page.html")
    tab = await open_tab(url)
    _, _, body = _split(await read_page(tab=tab))
    assert "# Example Money Market Fund" in body
    assert "Seven-day yield" in body
    assert "Host page heading" not in body


async def test_read_page_excludes_inert_templates_but_keeps_instantiated_content(open_tab, servers):
    tab = await open_tab(f"{servers.primary}/template-content/page.html")
    _, _, document = await get_document("read_page", tab=tab)
    before = await document.evaluate("document.querySelector('#article-template').innerHTML")
    _, _, body = _split(await read_page(tab=tab))

    assert "{{" not in body
    assert body == (
        "# News\n\nPublished news appears here.\n\nInstantiated article.\n\n"
        "Published component content.\n\nNews footer."
    )
    assert await document.evaluate("document.querySelector('#article-template').innerHTML") == before


async def test_save_page_content_excludes_inert_templates(open_tab, servers, tmp_path, monkeypatch):
    config = load_config().model_copy(deep=True)
    config.virtual_computer.home_dir = str(tmp_path)
    monkeypatch.setattr("tools.browser.save.load_config", lambda: config)
    tab = await open_tab(f"{servers.primary}/template-content/page.html")
    await save_page_content("news.md", tab=tab)

    saved = (tmp_path / "news.md").read_text()
    assert "{{" not in saved
    assert saved.count("Instantiated article.") == 1
    assert "Published component content." in saved
