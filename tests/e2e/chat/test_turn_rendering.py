"""E2E coverage for `<Turn>`-based rendering of nudges and compactions.

Two paths get exercised:

* **Live** — ``/api/chat`` is stubbed via ``page.route``; the test feeds
  the FE a canned SSE stream containing the events of interest
  (``user_message`` with ``is_nudge``, ``compaction``, mid-turn
  ``iteration`` splits) and asserts on the resulting DOM.
* **Resume** — an ``events.jsonl`` is seeded directly into the
  container; the FE loads it through the normal recent-conversations
  flow and the same assertions run against the resumed view.

No real LLM call is made. The stubbed SSE replaces the model output so
the tests stay deterministic and offline.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e.pages import ChatView, RecentConversations

CONV_DIR = "/var/lib/computron/conversations"
AGENT_NAME = "COMPUTRON"


# ── helpers ────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


def _sse_envelope(payload: dict, agent_id: str, *, ts: str | None = None,
                  depth: int = 0) -> dict:
    """Wrap a payload in the SSE envelope shape the FE expects.

    The FE's ``_flattenSseToEvent`` reads ``payload`` + the sibling
    metadata fields (agent_id, agent_name, timestamp, depth) and flattens
    them back into the flat events.jsonl shape that ``_buildTurns``
    consumes.
    """
    return {
        "payload": payload,
        "agent_id": agent_id,
        "agent_name": AGENT_NAME,
        "timestamp": ts or _now().isoformat(),
        "depth": depth,
    }


def _to_jsonl(items: list[dict]) -> str:
    return "".join(json.dumps(i) + "\n" for i in items)


def _seed_conversation(conv_id: str, events: list[dict],
                       title: str | None = None) -> None:
    """Write a flat events.jsonl + metadata.json into the container."""
    events_jsonl = _to_jsonl(events)
    meta = json.dumps({"title": title if title is not None else conv_id})
    script = (
        "import pathlib\n"
        f"d = pathlib.Path('{CONV_DIR}/{conv_id}')\n"
        "d.mkdir(parents=True, exist_ok=True)\n"
        f"(d / 'events.jsonl').write_text({events_jsonl!r})\n"
        f"(d / 'metadata.json').write_text({meta!r})\n"
    )
    container_exec(script)


def _cleanup(conv_id: str) -> None:
    container_exec(
        "import shutil, pathlib\n"
        f"p = pathlib.Path('{CONV_DIR}/{conv_id}')\n"
        "if p.exists(): shutil.rmtree(p)\n"
    )


def _flat_event(type_: str, evt_id: str, conv_id: str, *,
                agent_id: str, ts_offset: int = 0,
                base: datetime | None = None, **extra) -> dict:
    """Flat events.jsonl shape — used to seed resume tests."""
    base = base or _now()
    return {
        "id": evt_id,
        "type": type_,
        "timestamp": (base + timedelta(seconds=ts_offset)).isoformat(),
        "conversation_id": conv_id,
        "agent_id": agent_id,
        "agent_name": AGENT_NAME,
        "depth": 0,
        **extra,
    }


def _compaction_stats() -> dict:
    """Stub stats so the chip's expand panel has something to render."""
    return {
        "context_before": 20000,
        "context_after": 8000,
        "context_limit": 30000,
        "saved_tokens": 12000,
        "saved_ratio": 0.6,
        "spanned_seconds": 4.0,
        "scope": {"user_messages": 1, "iterations": 1, "tool_results": 0},
        "sub_agents_spawned": 0,
        "summary_chars": 52,
        "summary_tokens": 13,
        "summary_lines": 1,
    }


# ── live path: stub /api/chat with canned SSE ──────────────────────────


@pytest.mark.e2e
def test_live_nudge_renders_as_inline_user_message(page: Page):
    """A streamed ``user_message`` with ``is_nudge=true`` shows up as a
    second ``message-user`` inside the same turn — i.e. a nudge does
    not start a new turn, it splits the existing assistant section."""
    chat = ChatView(page).goto().new_conversation()
    agent_id = "root.computron.1"

    stream = _to_jsonl([
        _sse_envelope({"type": "agent_started",
                       "agent_id": agent_id, "agent_name": AGENT_NAME,
                       "parent_agent_id": None}, agent_id),
        _sse_envelope({"type": "user_message",
                       "content": "kick off the work",
                       "attachments": [], "is_nudge": False}, agent_id),
        _sse_envelope({"type": "iteration", "iteration_index": 0,
                       "content": "starting on it", "thinking": None,
                       "tool_calls": []}, agent_id),
        _sse_envelope({"type": "user_message",
                       "content": "also handle case B",
                       "attachments": [], "is_nudge": True}, agent_id),
        _sse_envelope({"type": "iteration", "iteration_index": 1,
                       "content": "ok, including case B", "thinking": None,
                       "tool_calls": []}, agent_id),
        _sse_envelope({"type": "agent_completed",
                       "agent_id": agent_id, "agent_name": AGENT_NAME,
                       "status": "success"}, agent_id),
    ])

    page.route("**/api/chat", lambda route: route.fulfill(
        status=200,
        headers={"Content-Type": "application/x-ndjson"},
        body=stream,
    ))
    chat.send("kick off the work")
    chat.wait_streaming()

    # One turn, two user messages (initial + nudge), two assistant sections.
    expect(page.get_by_test_id("turn")).to_have_count(1)
    expect(page.get_by_test_id("message-user")).to_have_count(2)
    expect(page.get_by_test_id("message-assistant")).to_have_count(2)
    expect(page.get_by_test_id("message-user").nth(0)).to_contain_text(
        "kick off the work",
    )
    expect(page.get_by_test_id("message-user").nth(1)).to_contain_text(
        "also handle case B",
    )
    expect(page.get_by_test_id("message-assistant").nth(0)).to_contain_text(
        "starting on it",
    )
    expect(page.get_by_test_id("message-assistant").nth(1)).to_contain_text(
        "ok, including case B",
    )


@pytest.mark.e2e
def test_live_compaction_chip_splits_assistant_mid_turn(page: Page):
    """A compaction event arriving between two iterations of the same
    turn splits the assistant section: assistant₁, chip, assistant₂.
    The mid-turn case is the harder one — the chip placement logic
    needs to read ``kept_from_id`` and break the flush boundary."""
    chat = ChatView(page).goto().new_conversation()
    agent_id = "root.computron.1"

    stream = _to_jsonl([
        _sse_envelope({"type": "agent_started",
                       "agent_id": agent_id, "agent_name": AGENT_NAME,
                       "parent_agent_id": None}, agent_id),
        _sse_envelope({"type": "user_message",
                       "content": "do the long thing",
                       "attachments": [], "is_nudge": False}, agent_id),
        _sse_envelope({"id": "evt_iter_pre", "type": "iteration",
                       "iteration_index": 0,
                       "content": "first half of the response",
                       "thinking": None, "tool_calls": []}, agent_id),
        _sse_envelope({
            "type": "compaction",
            "kept_from_id": "evt_iter_post",
            "kept_to_id": "evt_iter_post",
            "summary_text": "earlier context summarized",
            "user_intent_summary": "user is testing compaction",
            "audit": {"model": "stub", "input_char_count": 4000,
                      "elapsed_seconds": 1.0},
            "stats": _compaction_stats(),
        }, agent_id),
        _sse_envelope({"id": "evt_iter_post", "type": "iteration",
                       "iteration_index": 1,
                       "content": "second half, post-compaction",
                       "thinking": None, "tool_calls": []}, agent_id),
        _sse_envelope({"type": "agent_completed",
                       "agent_id": agent_id, "agent_name": AGENT_NAME,
                       "status": "success"}, agent_id),
    ])

    page.route("**/api/chat", lambda route: route.fulfill(
        status=200,
        headers={"Content-Type": "application/x-ndjson"},
        body=stream,
    ))
    chat.send("do the long thing")
    chat.wait_streaming()

    expect(page.get_by_test_id("turn")).to_have_count(1)
    expect(page.get_by_test_id("compaction-chip")).to_have_count(1)
    expect(page.get_by_test_id("message-assistant")).to_have_count(2)
    expect(page.get_by_test_id("message-assistant").nth(0)).to_contain_text(
        "first half",
    )
    expect(page.get_by_test_id("message-assistant").nth(1)).to_contain_text(
        "second half",
    )
    # Chip lands in the DOM strictly between the two assistants.
    boxes = page.locator(
        "[data-testid='message-assistant'], [data-testid='compaction-row']",
    )
    expect(boxes.nth(0)).to_have_attribute("data-testid", "message-assistant")
    expect(boxes.nth(1)).to_have_attribute("data-testid", "compaction-row")
    expect(boxes.nth(2)).to_have_attribute("data-testid", "message-assistant")


# ── resume path: seed events.jsonl ─────────────────────────────────────


@pytest.mark.e2e
def test_resume_nudge_renders_inline(page: Page):
    """Loading a conversation whose log contains a nudge user_message
    rebuilds the same Turn structure the live path produces."""
    conv_id = "e2e-turn-resume-nudge"
    base = _now()
    agent_id = "root.computron.1"
    events = [
        _flat_event("agent_started", "evt_start", conv_id,
                    agent_id=agent_id, ts_offset=0, base=base,
                    parent_agent_id=None),
        _flat_event("user_message", "evt_u1", conv_id,
                    agent_id=agent_id, ts_offset=1, base=base,
                    content="run a long task", attachments=[],
                    is_nudge=False),
        _flat_event("iteration", "evt_i1", conv_id,
                    agent_id=agent_id, ts_offset=2, base=base,
                    iteration_index=0, content="starting…",
                    thinking=None, tool_calls=[]),
        _flat_event("user_message", "evt_u2", conv_id,
                    agent_id=agent_id, ts_offset=3, base=base,
                    content="also do step two", attachments=[],
                    is_nudge=True),
        _flat_event("iteration", "evt_i2", conv_id,
                    agent_id=agent_id, ts_offset=4, base=base,
                    iteration_index=1, content="step two done",
                    thinking=None, tool_calls=[]),
        _flat_event("agent_completed", "evt_done", conv_id,
                    agent_id=agent_id, ts_offset=5, base=base,
                    status="success"),
    ]
    _seed_conversation(conv_id, events)
    try:
        ChatView(page).goto()
        RecentConversations(page).open_by_title(conv_id)
        expect(page.get_by_test_id("turn")).to_have_count(1)
        expect(page.get_by_test_id("message-user")).to_have_count(2)
        expect(page.get_by_test_id("message-assistant")).to_have_count(2)
        expect(page.get_by_test_id("message-user").nth(0)).to_contain_text(
            "run a long task",
        )
        expect(page.get_by_test_id("message-user").nth(1)).to_contain_text(
            "also do step two",
        )
        # The nudge user_message must sit *between* the two assistant
        # sections — not at the start of the turn and not at the end.
        rows = page.locator(
            "[data-testid='message-user'], [data-testid='message-assistant']",
        )
        expect(rows.nth(0)).to_have_attribute("data-testid", "message-user")
        expect(rows.nth(1)).to_have_attribute("data-testid", "message-assistant")
        expect(rows.nth(2)).to_have_attribute("data-testid", "message-user")
        expect(rows.nth(3)).to_have_attribute("data-testid", "message-assistant")
    finally:
        _cleanup(conv_id)


@pytest.mark.e2e
def test_resume_mid_turn_compaction_splits_assistant(page: Page):
    """Compaction event sitting between two iterations of the same
    turn must split the assistant section into two on resume — the
    chip's ``kept_from_id`` points to the second iteration."""
    conv_id = "e2e-turn-resume-mid-compaction"
    base = _now()
    agent_id = "root.computron.1"
    events = [
        _flat_event("agent_started", "evt_start", conv_id,
                    agent_id=agent_id, ts_offset=0, base=base,
                    parent_agent_id=None),
        _flat_event("user_message", "evt_u1", conv_id,
                    agent_id=agent_id, ts_offset=1, base=base,
                    content="kick off long work", attachments=[],
                    is_nudge=False),
        _flat_event("iteration", "evt_i1", conv_id,
                    agent_id=agent_id, ts_offset=2, base=base,
                    iteration_index=0, content="pre-compaction work",
                    thinking=None, tool_calls=[]),
        _flat_event("compaction", "evt_c1", conv_id,
                    agent_id=agent_id, ts_offset=3, base=base,
                    kept_from_id="evt_i2", kept_to_id="evt_i2",
                    summary_text="prior context summarized",
                    user_intent_summary="user is exercising compaction",
                    audit={"model": "stub", "input_char_count": 4000,
                           "elapsed_seconds": 1.0},
                    stats=_compaction_stats()),
        _flat_event("iteration", "evt_i2", conv_id,
                    agent_id=agent_id, ts_offset=4, base=base,
                    iteration_index=1, content="post-compaction work",
                    thinking=None, tool_calls=[]),
        _flat_event("agent_completed", "evt_done", conv_id,
                    agent_id=agent_id, ts_offset=5, base=base,
                    status="success"),
    ]
    _seed_conversation(conv_id, events)
    try:
        ChatView(page).goto()
        RecentConversations(page).open_by_title(conv_id)
        expect(page.get_by_test_id("turn")).to_have_count(1)
        expect(page.get_by_test_id("compaction-chip")).to_have_count(1)
        expect(page.get_by_test_id("message-assistant")).to_have_count(2)
        expect(page.get_by_test_id("message-assistant").nth(0)).to_contain_text(
            "pre-compaction",
        )
        expect(page.get_by_test_id("message-assistant").nth(1)).to_contain_text(
            "post-compaction",
        )
        boxes = page.locator(
            "[data-testid='message-assistant'], "
            "[data-testid='compaction-row']",
        )
        expect(boxes.nth(0)).to_have_attribute(
            "data-testid", "message-assistant",
        )
        expect(boxes.nth(1)).to_have_attribute(
            "data-testid", "compaction-row",
        )
        expect(boxes.nth(2)).to_have_attribute(
            "data-testid", "message-assistant",
        )
    finally:
        _cleanup(conv_id)


@pytest.mark.e2e
def test_resume_sub_agent_renders_spawn_card_and_network(page: Page):
    """Loading a conversation that spawned a sub-agent must reconstruct:
      - the spawn card inline in the chat (driven by the persisted
        spawn_requested event + the sub-agent's correlation_id),
      - the network indicator showing the sub-agent,
      - the sub-agent's instruction in its activity view.
    Regression: before the resume replay landed, only synthetic agents
    were dispatched on resume so childIds / correlation lookups failed
    and the spawn card never rendered."""
    conv_id = "e2e-turn-resume-sub-agent"
    base = _now()
    root_id = "root.computron.1"
    sub_id = "root.computron.1.alpha.1"
    correlation = "corr-abc"
    events = [
        _flat_event("agent_started", "evt_root", conv_id,
                    agent_id=root_id, ts_offset=0, base=base,
                    parent_agent_id=None),
        _flat_event("user_message", "evt_u", conv_id,
                    agent_id=root_id, ts_offset=1, base=base,
                    content="delegate this", attachments=[],
                    is_nudge=False),
        _flat_event("iteration", "evt_i1", conv_id,
                    agent_id=root_id, ts_offset=2, base=base,
                    iteration_index=0, content="spawning",
                    thinking=None,
                    tool_calls=[{"id": "tc-spawn", "name": "spawn_agent",
                                 "arguments": {"agent_name": "alpha"}}]),
        _flat_event("spawn_requested", "evt_sr", conv_id,
                    agent_id=root_id, ts_offset=3, base=base,
                    correlation_id=correlation),
        {
            "id": "evt_sub_start", "type": "agent_started",
            "timestamp": (base + timedelta(seconds=4)).isoformat(),
            "conversation_id": conv_id, "agent_id": sub_id,
            "agent_name": "ALPHA", "parent_agent_id": root_id,
            "correlation_id": correlation, "depth": 1,
            "instruction": "Compute 7*6 and report",
        },
        {
            "id": "evt_sub_iter", "type": "iteration",
            "timestamp": (base + timedelta(seconds=5)).isoformat(),
            "conversation_id": conv_id, "agent_id": sub_id,
            "agent_name": "ALPHA", "depth": 1, "iteration_index": 0,
            "content": "42", "thinking": None, "tool_calls": [],
        },
        {
            "id": "evt_sub_done", "type": "agent_completed",
            "timestamp": (base + timedelta(seconds=6)).isoformat(),
            "conversation_id": conv_id, "agent_id": sub_id,
            "agent_name": "ALPHA", "depth": 1, "status": "success",
        },
        _flat_event("iteration", "evt_i2", conv_id,
                    agent_id=root_id, ts_offset=7, base=base,
                    iteration_index=1, content="the answer is 42",
                    thinking=None, tool_calls=[]),
        _flat_event("agent_completed", "evt_root_done", conv_id,
                    agent_id=root_id, ts_offset=8, base=base,
                    status="success"),
    ]
    _seed_conversation(conv_id, events)
    try:
        ChatView(page).goto()
        RecentConversations(page).open_by_title(conv_id)
        # Chat side: one user prompt (root's), spawn card visible, the
        # sub-agent's instruction must NOT appear as a phantom user.
        expect(page.get_by_test_id("turn")).to_have_count(1)
        expect(page.get_by_test_id("message-user")).to_have_count(1)
        expect(page.get_by_test_id("message-user")).to_contain_text(
            "delegate this",
        )
        expect(page.get_by_test_id("spawn-card")).to_be_visible()
        expect(page.get_by_test_id("spawn-card")).to_contain_text("ALPHA")
        # Network side: indicator shows 2 agents (root + sub).
        expect(page.get_by_test_id("network-indicator")).to_be_visible()
        expect(page.get_by_test_id("network-indicator")).to_contain_text(
            "2 agents",
        )
        # Sub-agent's activity view: instruction restored from event log.
        page.get_by_test_id("spawn-card-row").first.click()
        expect(page.get_by_test_id("agent-activity-title")).to_contain_text(
            "ALPHA",
        )
        expect(page.get_by_test_id("instruction-toggle")).to_contain_text(
            "Compute 7*6 and report",
        )
    finally:
        _cleanup(conv_id)
