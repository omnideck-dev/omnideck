"""Unit tests for the latest-per-tab browser snapshot sidecar."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conversations import BrowserTabsWriter, load_browser_tabs
from sdk.events import AgentEvent, BrowserScreenshotPayload, ContentPayload


@pytest.fixture()
def _conv_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        "conversations._store._get_conversations_dir", lambda: tmp_path,
    )
    return tmp_path


def _shot(tab_id: int, url: str, screenshot: str = "png==") -> AgentEvent:
    return AgentEvent(payload=BrowserScreenshotPayload(
        type="browser_screenshot", url=url, title=url, screenshot=screenshot,
        tab_id=tab_id,
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


def test_sidecar_holds_agent_id_for_restore(_conv_dir: Path) -> None:
    """The UI dispatches the restored snapshot onto its owning agent."""
    BrowserTabsWriter("c1").handle_event(_shot(1, "https://a.example"))
    (tab,) = load_browser_tabs("c1")
    assert tab["agent_id"] == "root.a.1"
    assert json.loads(
        (_conv_dir / "c1" / "browser_tabs.json").read_text(encoding="utf-8"),
    )["1"]["tab_id"] == "1"
