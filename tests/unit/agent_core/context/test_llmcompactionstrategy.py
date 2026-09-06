"""Tests for LLMCompactionStrategy and related helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_core.context import ConversationHistory
from agent_runtime._compaction import LLMCompactionStrategy
from agent_core.context._models import ContextStats
from agent_runtime._compaction import (
    _SUMMARY_PREFIX,
    _extract_prior_summary,
    _find_first_user,
    _serialize_messages,
)
from agent_core.events import CompactionPayload
from agent_core.providers import ProviderError


def _make_stats(fill_ratio: float = 0.8) -> ContextStats:
    return ContextStats(context_used=int(fill_ratio * 1000), context_limit=1000)


def _build_history(messages: list[dict]) -> ConversationHistory:
    return ConversationHistory(messages)


# ── compaction publishes a CompactionPayload ────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_compaction_publishes_payload_and_derived_view_shows_summary():
    """apply() publishes a CompactionPayload; the derived view picks it up
    on the next read and shows the summary marker at index 1."""
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "original request"},
        *[{"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"} for i in range(10)],
        {"role": "user", "content": "recent user"},
        {"role": "assistant", "content": "recent assistant"},
    ]
    history = _build_history(messages)
    strategy = LLMCompactionStrategy(threshold=0.5, keep_recent_groups=1, summary_model="test-model")

    published_payloads: list = []
    captured = MagicMock(side_effect=lambda evt: published_payloads.append(evt.payload))

    with patch.object(strategy, "_summarize", new_callable=AsyncMock) as mock_summarize, \
         patch("agent_runtime._compaction.publish_event", captured), \
         patch("agent_runtime._compaction.load_settings",
               return_value={"compaction_provider": "test-provider", "compaction_model": "test-model", "compaction_options": {}}):
        mock_summarize.return_value = ("This is the summary.", "test-model")
        await strategy.apply(history, _make_stats(0.8))

    compactions = [p for p in published_payloads if isinstance(p, CompactionPayload)]
    assert len(compactions) == 1
    assert compactions[0].summary_text == "This is the summary."
    assert compactions[0].kept_from_id  # bound to an iteration event id
    assert compactions[0].kept_to_id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_compaction_failure_raises_with_user_facing_message():
    """When the summarizer call fails, apply() raises a ProviderError carrying a
    user-facing message instead of silently skipping, so the turn loop surfaces
    it and the user can fix the compaction model and retry."""
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "original request"},
        *[{"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"} for i in range(10)],
        {"role": "user", "content": "recent user"},
        {"role": "assistant", "content": "recent assistant"},
    ]
    history = _build_history(messages)
    strategy = LLMCompactionStrategy(threshold=0.5, keep_recent_groups=1, summary_model="test-model")

    with patch.object(strategy, "_summarize", new_callable=AsyncMock) as mock_summarize, \
         patch("agent_runtime._compaction._unload_model", new_callable=AsyncMock), \
         patch("agent_runtime._compaction.load_settings",
               return_value={"compaction_provider": "test-provider", "compaction_model": "test-model", "compaction_options": {}}):
        mock_summarize.side_effect = ProviderError("rate limited (status code: 429)", retryable=True)
        with pytest.raises(ProviderError) as excinfo:
            await strategy.apply(history, _make_stats(0.8))

    assert excinfo.value.retryable is True
    message = str(excinfo.value)
    assert "test-model" in message
    assert "rate limited" in message
    assert "Settings" in message


@pytest.mark.unit
@pytest.mark.asyncio
async def test_compaction_does_not_mutate_history_directly():
    """The strategy never mutates history — it only publishes an event."""
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "old response"},
        {"role": "user", "content": "do something"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "run_bash_cmd", "arguments": "{}"}}
        ]},
        {"role": "tool", "content": "tool result", "tool_name": "run_bash_cmd"},
        {"role": "user", "content": "now fix it"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "run_bash_cmd", "arguments": "{}"}}
        ]},
        {"role": "tool", "content": "fixed", "tool_name": "run_bash_cmd"},
        {"role": "assistant", "content": "Done!"},
    ]
    history = _build_history(messages)
    strategy = LLMCompactionStrategy(threshold=0.5, keep_recent_groups=2, summary_model="test-model")

    events_before = list(history.recorded_events)

    with patch.object(strategy, "_summarize", new_callable=AsyncMock) as mock_summarize, \
         patch("agent_runtime._compaction.publish_event"), \
         patch("agent_runtime._compaction.load_settings",
               return_value={"compaction_provider": "test-provider", "compaction_model": "test-model", "compaction_options": {}}):
        mock_summarize.return_value = ("Summary text.", "test-model")
        await strategy.apply(history, _make_stats(0.8))

    # No mutation: the in-memory event log is unchanged because the
    # CompactionPayload publish was mocked (in production it would
    # flow back through handle_event).
    assert history.recorded_events == events_before


# ── _serialize_messages: summary skip is role-agnostic ─────────────────


@pytest.mark.unit
def test_serialize_skips_assistant_role_summary():
    """Summary with role=assistant (new format) should be skipped."""
    messages = [
        {"role": "assistant", "content": _SUMMARY_PREFIX + "old summary"},
        {"role": "user", "content": "hello"},
    ]
    result = _serialize_messages(messages)
    assert "old summary" not in result
    assert "User: hello" in result


@pytest.mark.unit
def test_serialize_skips_user_role_summary_legacy():
    """Summary with role=user (legacy format) should also be skipped."""
    messages = [
        {"role": "user", "content": _SUMMARY_PREFIX + "old summary"},
        {"role": "assistant", "content": "response"},
    ]
    result = _serialize_messages(messages)
    assert "old summary" not in result
    assert "Assistant: response" in result


# ── _extract_prior_summary ─────────────────────────────────────────────


@pytest.mark.unit
def test_extract_prior_summary_finds_assistant_role():
    messages = [
        {"role": "assistant", "content": _SUMMARY_PREFIX + "the summary"},
        {"role": "user", "content": "hello"},
    ]
    assert _extract_prior_summary(messages) == "the summary"


@pytest.mark.unit
def test_extract_prior_summary_finds_legacy_user_role():
    messages = [
        {"role": "user", "content": _SUMMARY_PREFIX + "legacy summary"},
    ]
    assert _extract_prior_summary(messages) == "legacy summary"


@pytest.mark.unit
def test_extract_prior_summary_returns_none_when_absent():
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    assert _extract_prior_summary(messages) is None


# ── _find_first_user ───────────────────────────────────────────────────


@pytest.mark.unit
def test_find_first_user_skips_assistant_summary():
    """An assistant-role summary should be invisible to _find_first_user."""
    messages = [
        {"role": "assistant", "content": _SUMMARY_PREFIX + "summary"},
        {"role": "user", "content": "real first"},
    ]
    idx, found = _find_first_user(messages)
    assert found is True
    assert idx == 1


@pytest.mark.unit
def test_find_first_user_skips_legacy_user_summary():
    """A legacy user-role summary should also be skipped."""
    messages = [
        {"role": "user", "content": _SUMMARY_PREFIX + "summary"},
        {"role": "user", "content": "real first"},
    ]
    idx, found = _find_first_user(messages)
    assert found is True
    assert idx == 1


@pytest.mark.unit
def test_find_first_user_finds_normal_first():
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    idx, found = _find_first_user(messages)
    assert found is True
    assert idx == 0


# ── CompactionPayload forensic stats ───────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_compaction_payload_carries_audit_fields():
    """The published CompactionPayload's stats carry the forensic fields:
    model, input_char_count, elapsed_seconds."""
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "original"},
        *[{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(8)],
        {"role": "user", "content": "recent"},
        {"role": "assistant", "content": "recent reply"},
    ]
    history = _build_history(messages)
    strategy = LLMCompactionStrategy(threshold=0.5, keep_recent_groups=1)

    payloads: list = []

    with patch.object(strategy, "_summarize", new_callable=AsyncMock) as mock_summarize, \
         patch("agent_runtime._compaction.publish_event",
               side_effect=lambda evt: payloads.append(evt.payload)), \
         patch("agent_runtime._compaction.load_settings",
               return_value={"compaction_provider": "test-provider", "compaction_model": "test-model", "compaction_options": {"temperature": 0.3}}):
        mock_summarize.return_value = ("Summary.", "test-model")
        await strategy.apply(history, _make_stats(0.8))

    compactions = [p for p in payloads if isinstance(p, CompactionPayload)]
    assert len(compactions) == 1
    stats = compactions[0].stats
    assert stats.model == "test-model"
    assert stats.input_char_count > 0
    assert stats.elapsed_seconds >= 0


# ── _unload_model (async subprocess) ────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unload_model_spawns_subprocess_and_awaits():
    """_unload_model should use create_subprocess_exec and await communicate()."""
    from agent_runtime._compaction import _unload_model

    with patch("agent_runtime._compaction.asyncio.create_subprocess_exec") as mock_csp:
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_csp.return_value = mock_proc

        await _unload_model("test-model")

        mock_csp.assert_called_once_with(
            "ollama", "stop", "test-model",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        mock_proc.communicate.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unload_model_handles_timeout():
    """_unload_model should kill the process on timeout."""
    from agent_runtime._compaction import _unload_model

    with patch("agent_runtime._compaction.asyncio.create_subprocess_exec") as mock_csp:
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(side_effect=TimeoutError)
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()
        mock_csp.return_value = mock_proc

        await _unload_model("test-model")

        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unload_model_handles_subprocess_error():
    """_unload_model should catch OSError during subprocess creation."""
    from agent_runtime._compaction import _unload_model

    with patch("agent_runtime._compaction.asyncio.create_subprocess_exec",
               side_effect=OSError("ollama not found")):
        # Should not raise — the exception is caught and logged.
        await _unload_model("test-model")


# ── _compute_stats ─────────────────────────────────────────────────────


def _evt(type_: str, agent_name: str, evt_id: str, ts: str,
         **extra) -> dict:
    return {
        "id": evt_id,
        "type": type_,
        "timestamp": ts,
        "conversation_id": "c1",
        "agent_id": "root.x.1",
        "agent_name": agent_name,
        "depth": 0,
        **extra,
    }


def _started(agent_id: str, agent_name: str, evt_id: str,
             ts: str = "2026-01-01T00:00:00") -> dict:
    """A depth-0 agent_started event — what marks an agent_id as part of
    the root thread for scoped_events / build_llm_view membership."""
    return {
        **_evt("agent_started", agent_name, evt_id, ts),
        "agent_id": agent_id,
        "parent_agent_id": None,
        "depth": 0,
    }


@pytest.mark.unit
def test_compute_stats_full_population():
    """All scope counts, savings math, and spanned_seconds populate
    when the event log has the right shape."""
    strategy = LLMCompactionStrategy(threshold=0.5, keep_recent_groups=1,
                                 summary_model="m")
    history = ConversationHistory(conversation_id="c1")
    history.seed_events([
        _started("root.x.1", "AGENT_A", "as1"),
        _evt("user_message", "AGENT_A", "u1", "2026-01-01T00:00:00"),
        _evt("iteration", "AGENT_A", "i1", "2026-01-01T00:00:05"),
        _evt("tool_result", "AGENT_A", "t1", "2026-01-01T00:00:10"),
        _evt("iteration", "AGENT_A", "i2", "2026-01-01T00:01:00"),
        _evt("tool_result", "AGENT_A", "t2", "2026-01-01T00:01:05"),
        _evt("iteration", "AGENT_A", "kept",
             "2026-01-01T00:01:30"),  # kept_from_id
    ])

    stats = strategy._compute_stats(
        history=history,
        kept_from_id="kept",
        context_before=20000,
        context_limit=30000,
        input_char_count=40000,  # 40000 // 4 = 10000 tokens replaced
        summary_text="line one\nline two\nline three",
        model="m",
        elapsed_seconds=0.0,
    )

    assert stats.scope.user_messages == 1
    assert stats.scope.iterations == 2
    assert stats.scope.tool_results == 2
    # spanned: 00:00:00 → 00:01:05 = 65s (kept is excluded from the range)
    assert stats.spanned_seconds == pytest.approx(65.0, abs=0.01)
    # "line one\nline two\nline three" = 28 chars, 7 tokens, 3 lines
    assert stats.summary_chars == 28
    assert stats.summary_tokens == 7
    assert stats.summary_lines == 3
    # context_after = max(0, 20000 - 10000 + 7) = 10007
    assert stats.context_after == 10007
    assert stats.saved_tokens == 20000 - 10007
    assert stats.saved_ratio == pytest.approx(
        (20000 - 10007) / 20000, rel=1e-3,
    )


@pytest.mark.unit
def test_compute_stats_cross_turn_agent_id_suffix():
    """Iterations from earlier turns (agent_id ends in .1) must be
    counted when compaction fires on a later turn (agent_id ends in .2).
    Both turns are depth-0 agents, so the root-view scope spans them
    regardless of the per-turn ``.N`` agent_id suffix."""
    strategy = LLMCompactionStrategy(threshold=0.5, keep_recent_groups=1,
                                 summary_model="m")
    history = ConversationHistory(conversation_id="c1")
    history.seed_events([
        _started("root.agent_a.1", "AGENT_A", "as1"),
        {**_evt("user_message", "AGENT_A", "u1", "2026-01-01T00:00:00"),
         "agent_id": "root.agent_a.1"},
        {**_evt("iteration", "AGENT_A", "i1", "2026-01-01T00:00:05"),
         "agent_id": "root.agent_a.1"},
        _started("root.agent_a.2", "AGENT_A", "as2", "2026-01-01T00:01:00"),
        {**_evt("user_message", "AGENT_A", "u2", "2026-01-01T00:01:00"),
         "agent_id": "root.agent_a.2"},
        {**_evt("iteration", "AGENT_A", "kept", "2026-01-01T00:01:05"),
         "agent_id": "root.agent_a.2"},
    ])

    stats = strategy._compute_stats(
        history=history,
        kept_from_id="kept",
        context_before=10000,
        context_limit=30000,
        input_char_count=4000,
        summary_text="s",
        model="m",
        elapsed_seconds=0.0,
    )

    assert stats.scope.user_messages == 2  # both turns
    assert stats.scope.iterations == 1     # only the prior turn's iteration


@pytest.mark.unit
def test_resolve_kept_bounds_cross_turn_agent_id_suffix():
    """Regression: _resolve_kept_bounds must scope by the root thread, not
    a single agent_id. A fresh agent_id is minted every turn (e.g. ".1",
    ".2", ".3"); scoping to one id would only count the current turn's
    iterations and prevent compaction from ever firing in a multi-turn
    conversation."""
    strategy = LLMCompactionStrategy(threshold=0.5, keep_recent_groups=2,
                                 summary_model="m")
    history = ConversationHistory(conversation_id="c1")
    history.seed_events([
        _started("root.agent_a.1", "AGENT_A", "as1"),
        {**_evt("user_message", "AGENT_A", "u1", "2026-01-01T00:00:00"),
         "agent_id": "root.agent_a.1"},
        {**_evt("iteration", "AGENT_A", "i1", "2026-01-01T00:00:05"),
         "agent_id": "root.agent_a.1"},
        _started("root.agent_a.2", "AGENT_A", "as2", "2026-01-01T00:01:00"),
        {**_evt("user_message", "AGENT_A", "u2", "2026-01-01T00:01:00"),
         "agent_id": "root.agent_a.2"},
        {**_evt("iteration", "AGENT_A", "i2", "2026-01-01T00:01:05"),
         "agent_id": "root.agent_a.2"},
        _started("root.agent_a.3", "AGENT_A", "as3", "2026-01-01T00:02:00"),
        {**_evt("user_message", "AGENT_A", "u3", "2026-01-01T00:02:00"),
         "agent_id": "root.agent_a.3"},
        {**_evt("iteration", "AGENT_A", "i3", "2026-01-01T00:02:05"),
         "agent_id": "root.agent_a.3"},
    ])

    kept_from_id, kept_to_id = strategy._resolve_kept_bounds(history)

    # keep_recent_groups=2 → anchor is the 2nd-from-last iteration (i2).
    assert kept_from_id == "i2"
    # kept_to is the most recent event for the agent (i3 here).
    assert kept_to_id == "i3"


@pytest.mark.unit
def test_resolve_kept_bounds_spans_mid_conversation_profile_switch():
    """Regression: switching to a different profile mid-conversation
    changes the root agent's name AND the profile segment of its
    agent_id, but every turn is still a depth-0 root agent. The
    iteration count must span the switch so compaction can fire on the
    new (e.g. smaller-context) profile instead of resetting to zero."""
    strategy = LLMCompactionStrategy(threshold=0.5, keep_recent_groups=2,
                                 summary_model="m")
    history = ConversationHistory(conversation_id="c1")
    history.seed_events([
        # Two turns under the original profile.
        _started("root.code_expert.1", "CODE EXPERT", "as1"),
        {**_evt("user_message", "CODE EXPERT", "u1", "2026-01-01T00:00:00"),
         "agent_id": "root.code_expert.1"},
        {**_evt("iteration", "CODE EXPERT", "i1", "2026-01-01T00:00:05"),
         "agent_id": "root.code_expert.1"},
        _started("root.code_expert.2", "CODE EXPERT", "as2",
                 "2026-01-01T00:01:00"),
        {**_evt("user_message", "CODE EXPERT", "u2", "2026-01-01T00:01:00"),
         "agent_id": "root.code_expert.2"},
        {**_evt("iteration", "CODE EXPERT", "i2", "2026-01-01T00:01:05"),
         "agent_id": "root.code_expert.2"},
        # User switches to a smaller-context profile; new name + agent_id.
        _started("root.small_window.3", "SMALL WINDOW", "as3",
                 "2026-01-01T00:02:00"),
        {**_evt("user_message", "SMALL WINDOW", "u3", "2026-01-01T00:02:00"),
         "agent_id": "root.small_window.3"},
        {**_evt("iteration", "SMALL WINDOW", "i3", "2026-01-01T00:02:05"),
         "agent_id": "root.small_window.3"},
    ])

    kept_from_id, kept_to_id = strategy._resolve_kept_bounds(history)

    # All three iterations are visible across the profile switch, so the
    # gate (keep_recent_groups=2) resolves real bounds instead of bailing.
    assert kept_from_id == "i2"
    assert kept_to_id == "i3"


@pytest.mark.unit
def test_compute_stats_second_compaction_skips_prior_range():
    """The range starts after the previous compaction event, not at the
    log head — earlier-compacted events are not re-counted."""
    strategy = LLMCompactionStrategy(threshold=0.5, keep_recent_groups=1,
                                 summary_model="m")
    history = ConversationHistory(conversation_id="c1")
    history.seed_events([
        _started("root.x.1", "AGENT_A", "as1"),
        _evt("user_message", "AGENT_A", "u1", "2026-01-01T00:00:00"),
        _evt("iteration", "AGENT_A", "i1", "2026-01-01T00:00:05"),
        _evt("compaction", "AGENT_A", "c1", "2026-01-01T00:00:10"),
        _evt("iteration", "AGENT_A", "i2", "2026-01-01T00:00:15"),
        _evt("iteration", "AGENT_A", "kept2", "2026-01-01T00:00:25"),
    ])

    stats = strategy._compute_stats(
        history=history,
        kept_from_id="kept2",
        context_before=10000,
        context_limit=30000,
        input_char_count=4000,
        summary_text="s",
        model="m",
        elapsed_seconds=0.0,
    )

    # Only i2 is in the range — u1 and i1 were summarized by c1.
    assert stats.scope.user_messages == 0
    assert stats.scope.iterations == 1
