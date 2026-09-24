"""Tests for Chrome launch policy and stealth init scripts.

These are marker tests — they verify that each critical section exists in the
script string so accidental deletions or regressions are caught early.  They
do NOT execute the JavaScript; runtime behavior is validated via live browser
testing against bot-detection sites.
"""

import pytest

from browser.core.launch import _ANTI_BOT_SCRIPT, _chrome_args, _launch_options

# ---------------------------------------------------------------------------
# Webdriver patch — the only patch needed for real Chrome
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWebdriverPatch:
    """navigator.webdriver removal.

    The property is deleted entirely so navigator.webdriver is undefined,
    matching a real non-automated browser.  Redefining it as false is
    detectable by fp-collect which checks for existence, not just value.
    """

    def test_deletes_prototype_property(self):
        assert "delete Navigator.prototype.webdriver" in _ANTI_BOT_SCRIPT

    def test_deletes_instance_property(self):
        assert "delete navigator.webdriver" in _ANTI_BOT_SCRIPT

    def test_does_not_redefine_property(self):
        assert "Object.defineProperty(navigator, 'webdriver'" not in _ANTI_BOT_SCRIPT
        assert "Object.defineProperty(Navigator.prototype, 'webdriver'" not in _ANTI_BOT_SCRIPT

    def test_has_make_native_helper(self):
        assert "_makeNative" in _ANTI_BOT_SCRIPT


# ---------------------------------------------------------------------------
# Chrome args
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestChromeArgs:
    """Verify stealth-related Chrome flags are present."""

    def test_webrtc_ip_leak_prevention(self):
        assert "--webrtc-ip-handling-policy=disable_non_proxied_udp" in _chrome_args()

    def test_uses_system_chrome_when_supported(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("browser.core.launch.platform.machine", lambda: "x86_64")
        options = _launch_options(
            headless=False,
            chrome_args=[],
            downloads_path=None,
        )
        assert options["channel"] == "chrome"


@pytest.mark.unit
def test_drops_enable_automation_flag():
    """Playwright's default --enable-automation is removed, not re-added.

    The flag turns on Chrome's automation mode (a bot signal). The old
    --enable-automation=false arg was a no-op — Chromium keys on the flag's
    presence, not its value — so it is dropped in favour of ignore_default_args.
    """
    options = _launch_options(
        headless=False,
        chrome_args=[],
        downloads_path=None,
    )
    assert options["ignore_default_args"] == ["--enable-automation"]
    assert "--enable-automation=false" not in options["args"]
