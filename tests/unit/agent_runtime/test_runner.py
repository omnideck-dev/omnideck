"""Tests for the concrete application-level AgentRunner."""

from __future__ import annotations

import asyncio
from typing import Any
from sdk.turn import ExecutionResult
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_runtime import AgentRuntime, AgentRunner, AgentRunRequest, RunAttachment
from agent_runtime import _runner as runner_module
from agent_runtime import _factory as factory_module
from agents._agent_profiles import AgentProfile
from conversations import load_events_jsonl
from sdk.context import ConversationHistory
from sdk.events import (
    AgentCompletedPayload,
    AgentEvent,
    AgentStartedPayload,
    ContentPayload,
    ErrorPayload,
    agent_span,
    publish_event,
)
from sdk.turn import StopRequestedError, ToolLoopError


@pytest.fixture(autouse=True)
def _browser_runtime(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Keep agent-run tests isolated from the process Browser runtime."""
    monkeypatch.setattr(factory_module, "get_provider", lambda _: MagicMock())
    runtime = MagicMock()
    runtime.prepare_current_agent_browser = AsyncMock()
    monkeypatch.setattr(runner_module, "get_browser_runtime", lambda: runtime)
    return runtime


def _request(conversation_id: str) -> AgentRunRequest:
    return AgentRunRequest(
        conversation_id=conversation_id,
        message="hello",
        attachments=None,
        profile_id="profile-1",
    )


async def _load_empty_history(
    conversation_id: str,
) -> ConversationHistory:
    return ConversationHistory(conversation_id=conversation_id)


async def _run(conversation_id: str) -> list[AgentEvent]:
    seen: list[AgentEvent] = []
    runtime = AgentRuntime(conversation_loader=_load_empty_history)
    handle = await runtime.start(_request(conversation_id))
    seen = [record.event async for record in handle.events()]
    return seen


def _profile() -> AgentProfile:
    return AgentProfile(
        id="profile-1",
        name="Test",
        provider="ollama",
        model="test-model",
        system_prompt="test",
        skills=[],
    )


def test_attachments_produce_model_text_and_structured_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Attachment setup retains both model paths and user-facing metadata."""
    paths = iter(["/virt/uploads/a.png", "/virt/uploads/b.csv"])
    monkeypatch.setattr(runner_module, "receive_attachment", lambda **_: next(paths))
    attachments = [
        RunAttachment(base64_encoded="aaaa", content_type="image/png", filename="a.png"),
        RunAttachment(base64_encoded="bbbb", content_type="text/csv", filename="b.csv"),
    ]

    text, attachments = runner_module._augment_message_with_attachments(
        "describe these",
        attachments,
    )

    assert "/virt/uploads/a.png" in text
    assert "/virt/uploads/b.csv" in text
    assert [item.filename for item in attachments] == ["a.png", "b.csv"]
    assert [item.path for item in attachments] == [
        "/virt/uploads/a.png",
        "/virt/uploads/b.csv",
    ]


def test_attachment_without_filename_falls_back_to_unnamed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing browser filenames still produce useful attachment records."""
    monkeypatch.setattr(
        runner_module,
        "receive_attachment",
        lambda **_: "/virt/uploads/synth.png",
    )

    _text, attachments = runner_module._augment_message_with_attachments(
        "look",
        [RunAttachment(base64_encoded="aaaa", content_type="image/png", filename=None)],
    )

    assert attachments[0].filename == "unnamed"
    assert attachments[0].path == "/virt/uploads/synth.png"


async def test_manager_stop_before_concrete_runner_starts_skips_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The manager-owned stop event reaches the runner's earliest checkpoint."""
    profile_lookups = 0

    def _unexpected_profile_lookup(_profile_id: str) -> None:
        nonlocal profile_lookups
        profile_lookups += 1

    monkeypatch.setattr(
        factory_module,
        "get_agent_profile",
        _unexpected_profile_lookup,
    )
    manager = AgentRuntime(conversation_loader=_load_empty_history)

    info = await manager.start(_request("early-stop"))
    stream = info.events(after_seq=0)
    info.stop()

    records = [record async for record in stream]

    assert profile_lookups == 0
    assert [record.event.payload.type for record in records] == ["turn_end"]


async def test_setup_failure_is_persisted_and_ends_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fallible setup runs inside turn_scope after persistence is subscribed."""
    conversation_id = "runner-setup-failure"

    def _explode(_profile_id: str) -> None:
        raise RuntimeError("profile store unavailable")

    monkeypatch.setattr(factory_module, "get_agent_profile", _explode)
    manager = AgentRuntime(conversation_loader=_load_empty_history)
    info = await manager.start(_request(conversation_id))
    stream = info.events(after_seq=0)

    records = [record async for record in stream]
    persisted = load_events_jsonl(conversation_id)

    assert [record.event.payload.type for record in records] == [
        "error",
        "turn_end",
    ]
    # turn_end is deliberately transport-only; the canonical error is what
    # must survive conversation resume with the same stable event identity.
    assert [event["type"] for event in persisted] == ["error"]
    assert records[0].event.id == persisted[0]["id"]


async def test_tool_loop_failure_is_not_duplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ToolLoopError keeps its specific error and one scope-owned turn_end."""
    monkeypatch.setattr(factory_module, "get_agent_profile", lambda _pid: _profile())

    async def _failing_execute(self, **_kwargs: Any) -> None:
        publish_event(
            AgentEvent(
                payload=ErrorPayload(
                    type="error",
                    message="usage limit reached",
                )
            )
        )
        raise ToolLoopError("usage limit reached")

    monkeypatch.setattr(runner_module.AgentExecutor, "execute", _failing_execute)

    seen = await _run("runner-tool-failure")
    errors = [event for event in seen if event.payload.type == "error"]

    assert len(errors) == 1
    assert errors[0].payload.message == "usage limit reached"
    assert [event.payload.type for event in seen].count("turn_end") == 1


async def test_published_events_are_forwarded_once_and_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner delivery includes nested lifecycle without duplicate events."""

    async def _fake_tool_loop(self, **_kwargs: Any) -> ExecutionResult:
        publish_event(
            AgentEvent(
                payload=ContentPayload(
                    type="content",
                    content="one",
                )
            )
        )
        await asyncio.sleep(0)
        async with agent_span("nested"):
            publish_event(
                AgentEvent(
                    payload=ContentPayload(
                        type="content",
                        content="secret",
                        thinking="hidden",
                    )
                )
            )

        return ExecutionResult("success")

    monkeypatch.setattr(factory_module, "get_agent_profile", lambda _pid: _profile())
    monkeypatch.setattr(runner_module.AgentExecutor, "execute", _fake_tool_loop)

    seen = await _run("runner-event-order")

    content = [(event.payload.content, event.payload.thinking) for event in seen if event.payload.type == "content"]
    assert content == [("one", None), ("secret", "hidden")]
    assert any(
        isinstance(event.payload, AgentStartedPayload) and event.payload.agent_name == "nested" for event in seen
    )
    completed_indexes = [index for index, event in enumerate(seen) if isinstance(event.payload, AgentCompletedPayload)]
    assert completed_indexes[-1] < len(seen) - 1
    assert seen[-1].payload.type == "turn_end"


async def test_runner_prepares_browser_from_agent_profile(
    monkeypatch: pytest.MonkeyPatch,
    _browser_runtime: MagicMock,
) -> None:
    """The application runner passes the selected profile to Browser runtime."""
    profile = _profile().model_copy(update={"browser_profile_id": "empty"})
    monkeypatch.setattr(factory_module, "get_agent_profile", lambda _pid: profile)
    monkeypatch.setattr(runner_module.AgentExecutor, "execute", AsyncMock(return_value=ExecutionResult("success")))

    await _run("runner-browser-profile")

    _browser_runtime.prepare_current_agent_browser.assert_awaited_once_with(
        agent_profile_id="profile-1",
        browser_profile_id="empty",
    )


async def test_stopped_root_lifecycle_precedes_turn_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stopped root records stopped completion before terminal delivery."""

    async def _stopped_tool_loop(self, **_kwargs: Any) -> None:
        publish_event(
            AgentEvent(
                payload=ContentPayload(
                    type="content",
                    content="partial",
                )
            )
        )
        raise StopRequestedError

    monkeypatch.setattr(factory_module, "get_agent_profile", lambda _pid: _profile())
    monkeypatch.setattr(runner_module.AgentExecutor, "execute", _stopped_tool_loop)

    seen = await _run("runner-stop-order")
    root_completed = [
        event
        for event in seen
        if isinstance(event.payload, AgentCompletedPayload) and event.payload.agent_name == "TEST"
    ]

    assert root_completed[-1].payload.status == "stopped"
    assert seen.index(root_completed[-1]) < len(seen) - 1
    assert seen[-1].payload.type == "turn_end"
