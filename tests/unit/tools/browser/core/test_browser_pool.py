"""Tests for the browser context pool (copy-on-create isolation)."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.unit.tools.browser.support.playwright_stubs import EventEmitterStub
from tools.browser.core.browser import Browser
from tools.browser.core.pool import (
    _scoped_browsers,
    browser_storage_state_scope,
    get_browser,
    release_agent_browser,
)

# All get_browser patches target pool.py's namespace since the names
# are bound there at import time, not looked up in sdk.events each call.
_MOD = "tools.browser.core.pool"


class _FakePage:
    def __init__(self, closed: bool = False) -> None:
        self._closed = closed

    def is_closed(self) -> bool:
        return self._closed

    def on(self, event: str, callback: Any) -> None:
        pass

    async def close(self) -> None:
        self._closed = True


class _FakeContext(EventEmitterStub):
    """Minimal stub for BrowserContext used by Browser."""

    def __init__(self, pages: list[_FakePage] | None = None) -> None:
        super().__init__()
        self.pages = pages or []
        self.browser = MagicMock()
        self._storage = {"cookies": [], "origins": []}
        self._closed = False

    async def new_page(self) -> _FakePage:
        # Real Playwright fires the context "page" event as the page is created.
        page = _FakePage()
        self.pages.append(page)
        self.emit("page", page)
        return page

    async def storage_state(self) -> dict[str, Any]:
        return dict(self._storage)

    async def close(self) -> None:
        self._closed = True

    async def set_extra_http_headers(self, headers: dict[str, str]) -> None:
        pass

    async def add_init_script(self, script: str) -> None:
        pass


def _make_browser(**kwargs: Any) -> Browser:
    """Create one Browser session with a fake context."""
    context = kwargs.pop("context", _FakeContext([_FakePage()]))
    b = Browser(context=context, extra_headers={"Accept-Language": "en"}, **kwargs)
    b._downloads_dir = "/tmp/dl"
    return b


def _make_host(contexts: list[_FakeContext] | None = None) -> MagicMock:
    """Create a process-host double that returns isolated Browser sessions."""
    host = MagicMock()
    session_contexts = contexts or [_FakeContext([])]
    host.create_session = AsyncMock(side_effect=[_make_browser(context=context) for context in session_contexts])
    return host


@pytest.fixture(autouse=True)
def _clean_pool():
    """Ensure the global pool is clean."""
    _scoped_browsers.clear()
    yield
    _scoped_browsers.clear()


async def test_agent_gets_ephemeral_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """A sub-agent gets an ephemeral context keyed by agent_id."""
    ephemeral_ctx = _FakeContext([])
    host = _make_host([ephemeral_ctx])

    # Sub-agent: depth > 0, so the key is agent_id, not conv_id.
    monkeypatch.setattr(f"{_MOD}.get_current_depth", lambda: 1)
    monkeypatch.setattr(f"{_MOD}.get_conversation_id", lambda: "conv-1")
    monkeypatch.setattr(f"{_MOD}.get_current_agent_id", lambda: "root.1")

    with patch(f"{_MOD}._get_browser_host", new_callable=AsyncMock, return_value=host):
        result = await get_browser()

    assert result._context is ephemeral_ctx
    assert "root.1" in _scoped_browsers
    assert result._downloads_dir == "/tmp/dl"


async def test_agent_reuses_existing_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated get_browser calls from the same agent return the same instance."""
    host = _make_host()

    monkeypatch.setattr(f"{_MOD}.get_current_depth", lambda: 1)
    monkeypatch.setattr(f"{_MOD}.get_conversation_id", lambda: "conv-1")
    monkeypatch.setattr(f"{_MOD}.get_current_agent_id", lambda: "root.web.1")

    with patch(f"{_MOD}._get_browser_host", new_callable=AsyncMock, return_value=host):
        first = await get_browser()
        second = await get_browser()

    assert first is second
    host.create_session.assert_awaited_once()


async def test_concurrent_agents_get_separate_contexts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two agents with different IDs get separate ephemeral contexts."""
    host = _make_host([_FakeContext([]), _FakeContext([])])

    monkeypatch.setattr(f"{_MOD}.get_current_depth", lambda: 1)
    monkeypatch.setattr(f"{_MOD}.get_conversation_id", lambda: "conv-1")

    with patch(f"{_MOD}._get_browser_host", new_callable=AsyncMock, return_value=host):
        monkeypatch.setattr(f"{_MOD}.get_current_agent_id", lambda: "task_a.1")
        first = await get_browser()

        monkeypatch.setattr(f"{_MOD}.get_current_agent_id", lambda: "task_b.2")
        second = await get_browser()

    assert first is not second
    assert first._context is not second._context
    assert "task_a.1" in _scoped_browsers
    assert "task_b.2" in _scoped_browsers


async def test_release_agent_browser_closes_context() -> None:
    """release_agent_browser closes the ephemeral context and removes it from the pool."""
    browser = _make_browser()
    _scoped_browsers["agent_x"] = browser

    await release_agent_browser("agent_x")

    assert "agent_x" not in _scoped_browsers
    assert browser._closed is True


async def test_release_nonexistent_agent_is_noop() -> None:
    """Releasing a browser for an agent that doesn't exist is a no-op."""
    await release_agent_browser("nonexistent")
    assert len(_scoped_browsers) == 0


async def test_root_agent_reuses_conversation_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Subsequent turns of a root agent reuse the conversation-scoped context."""
    host = _make_host()
    prior_ctx = _FakeContext([_FakePage()])
    prior_browser = Browser(context=prior_ctx, extra_headers={}, pw=None)
    prior_browser._downloads_dir = "/tmp/dl"
    _scoped_browsers["conv:abc-123"] = prior_browser

    # Root agent: depth 0, conv_id set — key is "conv:abc-123".
    monkeypatch.setattr(f"{_MOD}.get_current_depth", lambda: 0)
    monkeypatch.setattr(f"{_MOD}.get_conversation_id", lambda: "abc-123")
    monkeypatch.setattr(f"{_MOD}.get_current_agent_id", lambda: "root.computron_kimi.2")

    with patch(f"{_MOD}._get_browser_host", new_callable=AsyncMock, return_value=host):
        result = await get_browser()

    assert result is prior_browser
    assert "conv:abc-123" in _scoped_browsers
    host.create_session.assert_not_awaited()


async def test_different_conversation_gets_separate_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """A new conversation creates a fresh browser context, not the prior one."""
    host = _make_host()
    old_browser = Browser(context=_FakeContext([_FakePage()]), extra_headers={}, pw=None)
    old_browser._downloads_dir = "/tmp/dl"
    _scoped_browsers["conv:old-conv"] = old_browser

    monkeypatch.setattr(f"{_MOD}.get_current_depth", lambda: 0)
    monkeypatch.setattr(f"{_MOD}.get_conversation_id", lambda: "new-conv")
    monkeypatch.setattr(f"{_MOD}.get_current_agent_id", lambda: "root.computron_kimi.3")

    with patch(f"{_MOD}._get_browser_host", new_callable=AsyncMock, return_value=host):
        result = await get_browser()

    assert result is not old_browser
    assert "conv:new-conv" in _scoped_browsers
    assert "conv:old-conv" in _scoped_browsers


async def test_release_conversation_browser_by_key() -> None:
    """release_agent_browser with a conv: key releases the conversation context."""
    browser = _make_browser()
    _scoped_browsers["conv:target-conv"] = browser

    await release_agent_browser("conv:target-conv")

    assert "conv:target-conv" not in _scoped_browsers
    assert browser._closed is True


async def test_ephemeral_inherits_prepared_agent_storage_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Agent contexts lazily use the neutral seed bound by the application."""
    ephemeral_ctx = _FakeContext([])
    host = _make_host([ephemeral_ctx])
    saved_state = {
        "cookies": [{"name": "session", "value": "abc"}],
        "origins": [],
    }
    load_state = AsyncMock(return_value=saved_state)

    monkeypatch.setattr(f"{_MOD}.get_current_depth", lambda: 1)
    monkeypatch.setattr(f"{_MOD}.get_conversation_id", lambda: "conv-1")
    monkeypatch.setattr(f"{_MOD}.get_current_agent_id", lambda: "root.deep.1")

    with (
        browser_storage_state_scope(load_state),
        patch(f"{_MOD}._get_browser_host", new_callable=AsyncMock, return_value=host),
    ):
        await get_browser()

    load_state.assert_awaited_once_with()
    call_kwargs = host.create_session.call_args.kwargs
    assert call_kwargs["storage_state"]["cookies"] == [{"name": "session", "value": "abc"}]


async def test_existing_context_does_not_load_storage_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Saved state stays lazy when a conversation already has a Browser."""
    host = _make_host()
    existing = _make_browser()
    _scoped_browsers["conv:conv-1"] = existing
    load_state = AsyncMock()

    monkeypatch.setattr(f"{_MOD}.get_current_depth", lambda: 0)
    monkeypatch.setattr(f"{_MOD}.get_conversation_id", lambda: "conv-1")

    with (
        browser_storage_state_scope(load_state),
        patch(f"{_MOD}._get_browser_host", new_callable=AsyncMock, return_value=host),
    ):
        result = await get_browser()

    assert result is existing
    load_state.assert_not_awaited()
    host.create_session.assert_not_awaited()
