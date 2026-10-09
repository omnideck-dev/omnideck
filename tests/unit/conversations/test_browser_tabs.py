"""Unit tests for the per-tab browser snapshot file (browser_tabs.json)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conversations import BrowserTabsWriter, load_browser_tabs
from agent_core.events import AgentEvent, BrowserScreenshotPayload, ContentPayload


@pytest.fixture()
def _conv_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        "conversations._store._get_conversations_dir", lambda: tmp_path,
    )
    return tmp_path


def _shot(
    tab_id: int,
    url: str,
    screenshot: str = "png==",
    open_tab_ids: list[int] | None = None,
) -> AgentEvent:
    return AgentEvent(payload=BrowserScreenshotPayload(
        type="browser_screenshot", url=url, title=url, screenshot=screenshot,
        tab_id=tab_id, open_tab_ids=open_tab_ids,
    ), agent_id="root.a.1")


def _reconcile(open_tab_ids: list[int] | None) -> AgentEvent:
    """A screenshot-less event: a tab closed, so there's no page to capture."""
    return AgentEvent(payload=BrowserScreenshotPayload(
        type="browser_screenshot", url="", title="", screenshot=None,
        tab_id=None, open_tab_ids=open_tab_ids,
    ), agent_id="root.a.1")


def test_latest_snapshot_per_tab_wins(_conv_dir: Path) -> None:
    w = BrowserTabsWriter("c1")
    w.handle_event(_shot(1, "https://a.example", "first"))
    w.handle_event(_shot(1, "https://b.example", "second"))
    w.handle_event(_shot(2, "https://c.example", "other-tab"))

    tabs = {t["tab_id"]: t for t in load_browser_tabs("c1")}
    assert set(tabs) == {"1", "2"}
    assert tabs["1"]["screenshot"] == "second"
    assert tabs["1"]["url"] == "https://b.example"
    assert tabs["2"]["screenshot"] == "other-tab"


def test_tabs_survive_across_writer_instances(_conv_dir: Path) -> None:
    """A new turn gets a fresh writer; earlier tabs must not be lost."""
    BrowserTabsWriter("c1").handle_event(_shot(1, "https://a.example"))
    BrowserTabsWriter("c1").handle_event(_shot(2, "https://b.example"))

    tabs = {t["tab_id"] for t in load_browser_tabs("c1")}
    assert tabs == {"1", "2"}


def test_non_screenshot_events_ignored(_conv_dir: Path) -> None:
    w = BrowserTabsWriter("c1")
    w.handle_event(AgentEvent(payload=ContentPayload(type="content", content="x")))
    assert load_browser_tabs("c1") == []
    assert not (_conv_dir / "c1" / "browser_tabs.json").exists()


def test_load_missing_or_corrupt_returns_empty(_conv_dir: Path) -> None:
    assert load_browser_tabs("nope") == []
    d = _conv_dir / "bad"
    d.mkdir(parents=True)
    (d / "browser_tabs.json").write_text("{not json", encoding="utf-8")
    assert load_browser_tabs("bad") == []


def test_reconcile_prunes_closed_tab(_conv_dir: Path) -> None:
    """A reconcile-only event drops snapshots for tabs no longer open."""
    w = BrowserTabsWriter("c1")
    w.handle_event(_shot(1, "https://a.example"))
    w.handle_event(_shot(2, "https://b.example"))
    w.handle_event(_reconcile(open_tab_ids=[1]))

    tabs = {t["tab_id"] for t in load_browser_tabs("c1")}
    assert tabs == {"1"}


def test_shot_with_open_set_prunes_others(_conv_dir: Path) -> None:
    """A screenshot event also reconciles: tabs absent from its open set are pruned."""
    w = BrowserTabsWriter("c1")
    w.handle_event(_shot(1, "https://a.example"))
    w.handle_event(_shot(2, "https://b.example"))
    w.handle_event(_shot(3, "https://c.example", open_tab_ids=[3]))

    tabs = {t["tab_id"] for t in load_browser_tabs("c1")}
    assert tabs == {"3"}


def test_reconcile_without_open_set_is_noop(_conv_dir: Path) -> None:
    """Nothing to record and no open set to reconcile against writes no file."""
    BrowserTabsWriter("c1").handle_event(_reconcile(open_tab_ids=None))

    assert load_browser_tabs("c1") == []
    assert not (_conv_dir / "c1" / "browser_tabs.json").exists()


def test_saved_tab_keeps_its_agent_id(_conv_dir: Path) -> None:
    """The agent that captured a tab is stored with it, so a reloaded
    conversation can show each tab under the agent that opened it."""
    BrowserTabsWriter("c1").handle_event(_shot(1, "https://a.example"))
    (tab,) = load_browser_tabs("c1")
    assert tab["agent_id"] == "root.a.1"


def test_tabs_stored_keyed_by_tab_id(_conv_dir: Path) -> None:
    """On disk the file is a map from tab id to that tab's snapshot."""
    BrowserTabsWriter("c1").handle_event(_shot(1, "https://a.example"))
    stored = json.loads(
        (_conv_dir / "c1" / "browser_tabs.json").read_text(encoding="utf-8"),
    )
    assert set(stored) == {"1"}
    assert stored["1"]["tab_id"] == "1"
