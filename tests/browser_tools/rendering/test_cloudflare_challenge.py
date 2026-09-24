"""Anti-bot "Verify you are human" interstitials in rendered documents.

A full-page Cloudflare challenge blocks the site. The browser cannot get past
it, so it does not try: it detects the interstitial and leads the rendered document
with a banner that routes the agent to read the page with fetch_url instead. A
page that merely embeds a Turnstile widget must be left alone.
"""

from __future__ import annotations

from tools.browser import browse_page, read_page

from .._helpers import find_ref

_BANNER = "Cloudflare challenge detected"


def _interstitial_url(servers) -> str:
    return f"{servers.primary}/cloudflare-challenge/interstitial.html"


async def test_interstitial_returns_only_the_banner(open_tab, servers):
    tab = await open_tab(_interstitial_url(servers))
    rendered = await browse_page(tab=tab)

    assert _BANNER in rendered
    # The banner sends the agent to the fetch fallback, since the browser has no
    # way to clear the challenge itself.
    assert "fetch_url" in rendered
    # Only the banner comes back — no page snapshot, no refs to act on. Offering
    # refs would imply the agent can do something in the browser; it can't.
    assert find_ref(rendered) is None


async def test_read_page_reports_challenge_banner(open_tab, servers):
    tab = await open_tab(_interstitial_url(servers))
    text = await read_page(tab=tab)

    assert _BANNER in text
    assert "fetch_url" in text


async def test_url_token_variant_is_detected(open_tab, servers):
    # Cloudflare's newer variant has a generic title and no DOM scaffold — only
    # the __cf_chl token in the address bar identifies it. Detection must key on
    # the URL, and the banner must survive into browse_page's own snapshot.
    url = f"{servers.primary}/cloudflare-challenge/simple.html?__cf_chl_rt_tk=test"
    tab = await open_tab(url)
    rendered = await browse_page(tab=tab)

    assert _BANNER in rendered


async def test_same_page_without_token_is_not_flagged(open_tab, servers):
    # Control: the identical page without the token is an ordinary page.
    url = f"{servers.primary}/cloudflare-challenge/simple.html"
    tab = await open_tab(url)
    rendered = await browse_page(tab=tab)

    assert _BANNER not in rendered


async def test_embedded_turnstile_is_not_treated_as_a_challenge(open_tab, servers):
    # A content page embedding a Turnstile widget keeps its own rendered document and
    # gets no banner — only full-page interstitials are hijacked.
    url = f"{servers.primary}/embedded-turnstile/page.html"
    tab = await open_tab(url)
    rendered = await browse_page(tab=tab)

    assert _BANNER not in rendered
    assert find_ref(rendered, role="textbox", name="Email address") is not None
    assert find_ref(rendered, role="button", name="Sign in") is not None
