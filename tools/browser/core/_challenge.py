"""Detection of anti-bot interstitial ("Verify you are human") pages.

Some sites sit behind an anti-bot vendor that serves a full-page interstitial
instead of the real page. The automated browser cannot get past these: they
clear on a fingerprint/JS check the browser fails, not on anything the tools
can click. So this module does not try to solve them. It detects the
interstitial; the caller then replaces the page view with the vendor's banner —
a short message telling the agent the page is blocked and to read it with
fetch_url — instead of returning a blank page and a pile of useless refs.

Detection is pluggable. Each vendor is one detector in ``_DETECTORS`` that
returns a ``ChallengeInfo`` when it recognizes its interstitial, else None.
``detect_challenge`` tries each in turn and returns the first match. Adding a
vendor (DataDome, Akamai, PerimeterX, …) is a localized change here: write a
detector and append it. The browser wiring that consumes ``ChallengeInfo`` stays
vendor-agnostic. Cloudflare is the only vendor implemented today.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import NamedTuple

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Response

logger = logging.getLogger(__name__)


class ChallengeInfo(NamedTuple):
    """A detected anti-bot interstitial.

    Attributes:
        vendor: Short vendor id (e.g. ``"cloudflare"``) for annotations and logs.
        banner: Text to lead the page view with so the agent knows the page is
            blocked and reads it with fetch_url instead of acting on the page.
    """

    vendor: str
    banner: str


# A detector reports its vendor's interstitial as a ChallengeInfo, or None when
# the page isn't that vendor's block. Best-effort: it swallows its own probe
# errors and returns None rather than raising.
_Detector = Callable[["Page", "Response | None"], Awaitable["ChallengeInfo | None"]]


# ---------------------------------------------------------------------------
# Cloudflare
# ---------------------------------------------------------------------------

# Cloudflare rewrites the address bar to carry a challenge round-trip token
# while an interstitial is up (e.g. ?__cf_chl_rt_tk=..., __cf_chl_tk, ...).
# Present across challenge variants — including ones with a generic page title
# and none of the usual DOM scaffolding — so it's the most reliable
# DOM-independent signal.
_CF_URL_TOKEN = "__cf_chl"

# Values Cloudflare sets on the ``cf-mitigated`` response header when it serves
# an interstitial. Authoritative on a fresh navigation and independent of the
# challenge's (frequently redesigned) HTML.
_CF_MITIGATED_VALUES = frozenset({"challenge", "captcha", "managed"})

# Runs on the main frame and reports whether the page is a full-page Cloudflare
# interstitial. It keys only on markers unique to the managed block page — its
# title, or the challenge-scaffold element ids that Cloudflare's interstitial
# carries. A developer-embedded Turnstile widget (``.cf-turnstile`` /
# ``cf-turnstile-response`` on a normal page) has none of these, so a login
# form that embeds a widget is never mistaken for a full-page block.
_CF_DETECT_JS = """
() => {
  const title = (document.title || '').toLowerCase();
  const titleHit = title.includes('just a moment')
    || title.includes('attention required')
    || title.includes('verifying you are human');
  const el = document.querySelector(
    '#challenge-running, #challenge-stage, #challenge-form,'
    + ' #cf-challenge-running, #cf-please-wait, #trk_jschal_js'
  );
  return titleHit || !!el;
}
"""

# Shown in place of the page when a Cloudflare challenge is up. Kept to one
# short line: the agent only needs to know the page is blocked and to use
# fetch_url. Extra detail about why just distracts it.
_CF_BANNER = (
    "[Cloudflare challenge detected] This page is blocked by a Cloudflare "
    "challenge. Call fetch_url(url) to read its content instead."
)

_CF_INFO = ChallengeInfo(vendor="cloudflare", banner=_CF_BANNER)


def is_cloudflare_challenge_response(response: Response | None) -> bool:
    """True when a navigation *response* is a Cloudflare interstitial.

    Reads the ``cf-mitigated`` header — the version-independent signal that
    Cloudflare is serving a challenge rather than the real page.
    """
    if response is None:
        return False
    try:
        mitigated = (response.headers or {}).get("cf-mitigated", "").strip().lower()
    except Exception:  # noqa: BLE001 - header access is best-effort
        return False
    return mitigated in _CF_MITIGATED_VALUES


async def _detect_cloudflare(page: Page, response: Response | None) -> ChallengeInfo | None:
    """Detect a Cloudflare interstitial on *page*.

    Three signals, cheapest and most reliable first: the challenge token
    Cloudflare leaves in the URL, the ``cf-mitigated`` header on a fresh
    navigation *response*, then the interstitial's DOM markers (title / scaffold
    ids) for in-page challenges that carry no response.
    """
    if _CF_URL_TOKEN in (page.url or "") or is_cloudflare_challenge_response(response):
        return _CF_INFO
    try:
        if await page.main_frame.evaluate(_CF_DETECT_JS):
            return _CF_INFO
    except PlaywrightError:
        logger.debug("Cloudflare challenge probe failed", exc_info=True)
    return None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# Every anti-bot vendor is one detector. Add a vendor by writing one that returns
# a ChallengeInfo on a hit and appending it here; nothing downstream changes.
_DETECTORS: tuple[_Detector, ...] = (_detect_cloudflare,)


async def detect_challenge(
    page: Page, response: Response | None = None,
) -> ChallengeInfo | None:
    """Return info on the anti-bot interstitial blocking *page*, or None.

    Tries each registered detector in turn and returns the first match.
    Best-effort: a detector that raises is treated as no match, so one vendor's
    failure can't mask another or blow up the caller.
    """
    for detect in _DETECTORS:
        try:
            info = await detect(page, response)
        except Exception:  # noqa: BLE001 - detection is best-effort
            logger.debug("challenge detector failed", exc_info=True)
            continue
        if info is not None:
            return info
    return None


__all__ = [
    "ChallengeInfo",
    "detect_challenge",
    "is_cloudflare_challenge_response",
]
