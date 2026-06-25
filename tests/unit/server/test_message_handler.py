"""Unit tests for ``server.message_handler`` turn + attachment behavior."""

from __future__ import annotations

import pytest

from server import message_handler as mh


def test_augment_message_with_attachments_returns_text_and_structured_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The augment helper returns both the LLM-facing text and the structured
    attachments needed to populate a UserMessagePayload."""
    from agents.types import Data

    paths = iter(["/virt/uploads/a.png", "/virt/uploads/b.csv"])
    monkeypatch.setattr(mh, "receive_attachment", lambda **_: next(paths))

    data = [
        Data(base64_encoded="aaaa", content_type="image/png", filename="a.png"),
        Data(base64_encoded="bbbb", content_type="text/csv", filename="b.csv"),
    ]
    text, attachments = mh._augment_message_with_attachments("describe these", data)

    assert "describe these" in text
    assert "/virt/uploads/a.png" in text
    assert "/virt/uploads/b.csv" in text

    assert len(attachments) == 2
    a, b = attachments
    assert (a.filename, a.content_type, a.path) == ("a.png", "image/png", "/virt/uploads/a.png")
    assert (b.filename, b.content_type, b.path) == ("b.csv", "text/csv", "/virt/uploads/b.csv")


def test_augment_message_with_attachments_falls_back_to_unnamed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When an attachment has no filename, the attachment record still gets a name."""
    from agents.types import Data

    monkeypatch.setattr(mh, "receive_attachment", lambda **_: "/virt/uploads/synth.png")

    data = [Data(base64_encoded="aaaa", content_type="image/png", filename=None)]
    _text, attachments = mh._augment_message_with_attachments("look", data)

    assert len(attachments) == 1
    assert attachments[0].filename == "unnamed"
    assert attachments[0].path == "/virt/uploads/synth.png"


async def test_setup_failure_yields_error_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failure during agent setup (before the turn starts, so before any
    event sink exists) must reach the user as an error event + turn_end —
    not be silently swallowed by the producer-task cleanup."""
    from agents._agent_profiles import AgentProfile

    profile = AgentProfile(
        id="computron", name="Test", provider="ollama", model="m",
        system_prompt="t", skills=[],
    )
    monkeypatch.setattr(mh, "get_agent_profile", lambda _pid: profile)

    async def _boom(*_a, **_kw):
        raise RuntimeError("setup exploded")

    monkeypatch.setattr(mh, "build_agent_state", _boom)

    seen = []
    async for ev in mh.handle_user_message(
        "hi", data=None, profile_id="computron", conversation_id="setup-fail",
    ):
        seen.append(ev)

    types = [ev.payload.type for ev in seen]
    assert "error" in types
    assert types[-1] == "turn_end"


async def test_failed_turn_yields_single_error_and_turn_end(monkeypatch: pytest.MonkeyPatch) -> None:
    """A turn failure surfaces exactly once: run_turn publishes the error
    event and turn_scope closes the turn — the generator's catch-all must
    not append a second, generic error on top."""
    from agents._agent_profiles import AgentProfile
    from sdk.events import AgentEvent, ErrorPayload, publish_event
    from sdk.turn import ToolLoopError

    profile = AgentProfile(
        id="computron", name="Test", provider="ollama", model="m",
        system_prompt="t", skills=[],
    )
    monkeypatch.setattr(mh, "get_agent_profile", lambda _pid: profile)

    async def _failing_run_turn(**_kw):
        publish_event(AgentEvent(payload=ErrorPayload(
            type="error", message="usage limit reached",
        )))
        raise ToolLoopError("usage limit reached")

    monkeypatch.setattr(mh, "run_turn", _failing_run_turn)

    seen = []
    async for ev in mh.handle_user_message(
        "hi", data=None, profile_id="computron", conversation_id="turn-fail",
    ):
        seen.append(ev)

    types = [ev.payload.type for ev in seen]
    assert types.count("error") == 1
    assert types.count("turn_end") == 1
    errors = [ev for ev in seen if ev.payload.type == "error"]
    assert errors[0].payload.message == "usage limit reached"
