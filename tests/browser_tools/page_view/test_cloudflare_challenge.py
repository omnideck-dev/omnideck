"""Anti-bot "Verify you are human" interstitials in the page view.

A full-page Cloudflare challenge blocks the site. The browser cannot get past
it, so it does not try: it detects the interstitial and leads the page view
with a banner that routes the agent to read the page with fetch_url instead. A
page that merely embeds a Turnstile widget must be left alone.
"""

from __future__ import annotations

from tools.browser.read_content import read_page
from tools.browser.snapshot_tool import browse_page

from .._helpers import find_ref

_BANNER = "Cloudflare challenge detected"


def _interstitial_url(servers) -> str:
    return f"{servers.primary}/cloudflare-challenge/interstitial.html"


async def test_interstitial_returns_only_the_banner(browser_session, servers):
    tab = await browser_session.open(_interstitial_url(servers))
    view = await browse_page(tab=tab)

    assert _BANNER in view
    # The banner sends the agent to the fetch fallback, since the browser has no
    # way to clear the challenge itself.
    assert "fetch_url" in view
    # Only the banner comes back — no page snapshot, no refs to act on. Offering
    # refs would imply the agent can do something in the browser; it can't.
    assert find_ref(view) is None


async def test_read_page_reports_challenge_banner(browser_session, servers):
    tab = await browser_session.open(_interstitial_url(servers))
    text = await read_page(tab=tab)

    assert _BANNER in text
    assert "fetch_url" in text


async def test_url_token_variant_is_detected(browser_session, servers):
    # Cloudflare's newer variant has a generic title and no DOM scaffold — only
    # the __cf_chl token in the address bar identifies it. Detection must key on
    # the URL, and the banner must survive into browse_page's own snapshot.
    url = f"{servers.primary}/cloudflare-challenge/simple.html?__cf_chl_rt_tk=test"
    tab = await browser_session.open(url)
    view = await browse_page(tab=tab)

    assert _BANNER in view


async def test_same_page_without_token_is_not_flagged(browser_session, servers):
    # Control: the identical page without the token is an ordinary page.
    url = f"{servers.primary}/cloudflare-challenge/simple.html"
    tab = await browser_session.open(url)
    view = await browse_page(tab=tab)

    assert _BANNER not in view


async def test_embedded_turnstile_is_not_treated_as_a_challenge(browser_session, servers):
    # A content page embedding a Turnstile widget keeps its own page view and
    # gets no banner — only full-page interstitials are hijacked.
    url = f"{servers.primary}/embedded-turnstile/page.html"
    tab = await browser_session.open(url)
    view = await browse_page(tab=tab)

    assert _BANNER not in view
    assert find_ref(view, role="textbox", name="Email address") is not None
    assert find_ref(view, role="button", name="Sign in") is not None
