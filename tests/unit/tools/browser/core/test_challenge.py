"""Tests for anti-bot challenge detection helpers."""

from __future__ import annotations

from typing import Any

import pytest
from playwright.async_api import Error as PlaywrightError

from tools.browser.core._challenge import (
    ChallengeInfo,
    detect_challenge,
    is_cloudflare_challenge_response,
)


class _FakeMainFrame:
    def __init__(self, *, interstitial: Any) -> None:
        self._interstitial = interstitial

    async def evaluate(self, _script: str, _arg: Any = None) -> Any:
        if isinstance(self._interstitial, Exception):
            raise self._interstitial
        return self._interstitial


class _FakePage:
    def __init__(self, *, interstitial: Any, url: str = "https://site.test/x") -> None:
        self.main_frame = _FakeMainFrame(interstitial=interstitial)
        self.url = url


class _FakeResponse:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


@pytest.mark.unit
@pytest.mark.asyncio
async def test_detect_returns_cloudflare_for_dom_interstitial() -> None:
    page = _FakePage(interstitial=True)
    info = await detect_challenge(page)  # type: ignore[arg-type]
    assert info is not None
    assert info.vendor == "cloudflare"
    # The banner must route the agent to the fetch fallback.
    assert "fetch_url" in info.banner


@pytest.mark.unit
@pytest.mark.asyncio
async def test_detect_returns_none_for_normal_page() -> None:
    page = _FakePage(interstitial=False)
    assert await detect_challenge(page) is None  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_detect_swallows_playwright_error() -> None:
    # A probe that raises must be treated as "no challenge", not blow up.
    page = _FakePage(interstitial=PlaywrightError("context destroyed"))
    assert await detect_challenge(page) is None  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_detect_via_url_token_without_dom_markers() -> None:
    # The "Simple Page" variant has a generic title and no scaffold, but the
    # URL still carries the challenge token — detection must catch it.
    page = _FakePage(interstitial=False, url="https://www.site.test/a?__cf_chl_rt_tk=abc123")
    info = await detect_challenge(page)  # type: ignore[arg-type]
    assert info is not None
    assert info.vendor == "cloudflare"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_detect_via_cf_mitigated_header() -> None:
    page = _FakePage(interstitial=False)
    resp = _FakeResponse({"cf-mitigated": "challenge"})
    info = await detect_challenge(page, resp)  # type: ignore[arg-type]
    assert info is not None
    assert info.vendor == "cloudflare"


@pytest.mark.unit
def test_is_challenge_response_header_values() -> None:
    assert is_cloudflare_challenge_response(_FakeResponse({"cf-mitigated": "challenge"}))  # type: ignore[arg-type]
    assert is_cloudflare_challenge_response(_FakeResponse({"cf-mitigated": "CAPTCHA"}))  # type: ignore[arg-type]
    assert not is_cloudflare_challenge_response(_FakeResponse({}))  # type: ignore[arg-type]
    assert not is_cloudflare_challenge_response(_FakeResponse({"cf-mitigated": ""}))  # type: ignore[arg-type]
    assert not is_cloudflare_challenge_response(None)


@pytest.mark.unit
def test_challenge_info_carries_only_vendor_and_banner() -> None:
    # ChallengeInfo is the vendor-agnostic shape consumers depend on.
    info = ChallengeInfo(vendor="cloudflare", banner="hi")
    assert info.vendor == "cloudflare"
    assert info.banner == "hi"
