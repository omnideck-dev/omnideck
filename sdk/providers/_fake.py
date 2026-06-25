"""Deterministic in-process LLM provider for tests.

This provider lets the whole app run without any real LLM backend. It is
selected by ``get_provider`` when the ``MOCK_LLM`` environment
variable is set, so both ``/api/models`` and the chat tool-loop are served
from canned, deterministic behaviour.

Rather than guess intent from natural language, the fake reads an explicit
**directive protocol** embedded in the user message. A prompt is a sequence
of directives, each delimited by ``<<NAME ...>>`` ... ``<<END>>``:

    <<SAY>>text<<END>>             reply with this text (verbatim, multiline)
    <<TOOL name>>{json args}<<END>>  call tool *name* with JSON keyword args,
        e.g. ``<<TOOL run_bash_cmd>>{"cmd": "echo hi"}<<END>>`` or
        ``<<TOOL close_tab>>{"tab": 2}<<END>>``. Skill-gated tools (coder,
        browser) are loaded first. The ``tests.e2e._protocol`` helpers
        (``bash``, ``write_file``, ``open_url``, ``call_tool``, …) emit this.
    <<SPAWN profile|NAME>>...<<ENDSPAWN>>
        spawn_agent(profile); the body is itself a directive sequence that
        the sub-agent runs. ``profile`` defaults to the default profile when
        omitted; the optional ``|NAME`` sets the sub-agent's UI display name.
        SPAWN uses its own ``<<ENDSPAWN>>`` terminator so its body can contain
        nested ``<<END>>`` directives. Consecutive SPAWNs go out together as
        one round (one grouped spawn card).
    <<PARALLEL>><<TOOL ...>>...<<END>>...<<ENDPARALLEL>>
        emit the contained TOOL directives in a single response so the loop
        runs them concurrently (when parallel tool execution is enabled),
        letting tests exercise real tool-call races.
    <<FAIL>>message<<END>>          the agent loop raises ``message`` once the
        tool steps preceding this directive have completed — a genuine error
        status driven through the real loop.
    <<PROVIDERFAIL mid>>message<<END>>  the provider itself raises a
        ProviderError (e.g. a 429); ``mid`` fails partway through the stream,
        otherwise it fails before any output.
    <<SLOW>>                        bare marker (no body): text replies stream
        with a small per-chunk delay, giving UI tests a window to interact
        mid-stream (e.g. click Stop). Ignored by the directive planner.

Directives run in the order written: a plain TOOL directive is one tool call
per loop iteration (so two TOOLs never race), a PARALLEL block is one batch run
together, and any SAY text is returned once every tool directive has completed.
A prompt with no directives is echoed back verbatim.

Because the agent loop re-sends the full history on every call, the planner
is stateless: it counts the tool results already in the history to decide
which directive comes next.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncGenerator, Callable
from typing import Any

from ._models import (
    ChatDelta,
    ChatMessage,
    ChatResponse,
    LLMConfig,
    ModelInfo,
    ProviderError,
    ToolCall,
    ToolCallFunction,
)

# Models advertised by list_models(). Names are chosen so the setup wizard
# and provider tests, which match on fragments like "kimi-k2.5" and
# "qwen3.5", resolve a model without a real backend.
_FAKE_MODELS: list[ModelInfo] = [
    ModelInfo(name="kimi-k2.5:cloud", context_window=200_000, supports_thinking=True),
    ModelInfo(name="qwen3.5:cloud", context_window=128_000, supports_images=True),
    ModelInfo(name="gemma3:cloud", context_window=128_000, supports_images=True),
    ModelInfo(name="fake-model", context_window=32_000),
]

# Bare marker (no body / <<END>>): when present anywhere in the task, text
# replies stream with a small delay per chunk — gives UI tests a window to
# interact mid-stream (e.g. click Stop). Ignored by the directive planner.
_SLOW_RE = re.compile(r"<<SLOW>>", re.IGNORECASE)

# SPAWN and PARALLEL are block directives with their own terminators; the rest
# are simple <<NAME ...>>body<<END>> directives. SPAWN bodies are matched to
# their *balanced* <<ENDSPAWN>> (a depth counter, not a regex) so a SPAWN body
# may itself contain nested SPAWNs — multi-level delegation. FAIL and
# PROVIDERFAIL are control directives consumed by the planner rather than
# emitted as tool rounds (see _build_rounds): FAIL makes the agent loop raise
# after the rounds preceding it; PROVIDERFAIL makes the provider itself raise,
# modeling a real ProviderError (e.g. a 429).
_SPAWN_OPEN_RE = re.compile(r"<<SPAWN(?P<arg>[^>]*)>>", re.IGNORECASE)
_ENDSPAWN_RE = re.compile(r"<<ENDSPAWN>>", re.IGNORECASE)
_PARALLEL_OPEN_RE = re.compile(r"<<PARALLEL>>", re.IGNORECASE)
_ENDPARALLEL_RE = re.compile(r"<<ENDPARALLEL>>", re.IGNORECASE)
_SIMPLE_RE = re.compile(
    r"<<(?P<name>SAY|TOOL|FAIL|PROVIDERFAIL)(?P<arg>[^>]*)>>(?P<body>.*?)<<END>>",
    re.IGNORECASE | re.DOTALL,
)

# Inner TOOL directives within a PARALLEL block. The block's calls are emitted
# in one response so the agent loop runs them concurrently (when parallel tool
# execution is enabled), letting tests exercise real tool-call races.
_INNER_TOOL_RE = re.compile(r"<<TOOL(?P<pname>[^>]*)>>(?P<pbody>.*?)<<END>>", re.IGNORECASE | re.DOTALL)


def _iter_directives(task: str) -> list[tuple[str, str, str]]:
    """Parse *task* into ordered (kind, arg, body) directive tuples.

    SPAWN blocks are matched to their balanced <<ENDSPAWN>> via a depth counter,
    so a SPAWN body may contain nested SPAWNs; the body is handed to the
    sub-agent verbatim and re-parsed when that sub runs. PARALLEL blocks run to
    their <<ENDPARALLEL>>. Everything else is a simple <<END>>-terminated
    directive.
    """
    out: list[tuple[str, str, str]] = []
    pos = 0
    n = len(task)
    while pos < n:
        sm = _SPAWN_OPEN_RE.search(task, pos)
        pm = _PARALLEL_OPEN_RE.search(task, pos)
        cm = _SIMPLE_RE.search(task, pos)
        candidates = [m for m in (sm, pm, cm) if m is not None]
        if not candidates:
            break
        m = min(candidates, key=lambda x: x.start())
        if m is sm:
            body_start = m.end()
            depth = 1
            j = body_start
            end_close = None
            while j < n:
                nxt_open = _SPAWN_OPEN_RE.search(task, j)
                nxt_close = _ENDSPAWN_RE.search(task, j)
                if nxt_close is None:
                    break  # unbalanced — treat the rest as the body
                if nxt_open is not None and nxt_open.start() < nxt_close.start():
                    depth += 1
                    j = nxt_open.end()
                else:
                    depth -= 1
                    if depth == 0:
                        end_close = nxt_close
                        break
                    j = nxt_close.end()
            if end_close is None:
                out.append(("SPAWN", m.group("arg"), task[body_start:]))
                break
            out.append(("SPAWN", m.group("arg"), task[body_start:end_close.start()]))
            pos = end_close.end()
        elif m is pm:
            close = _ENDPARALLEL_RE.search(task, m.end())
            if close is None:
                out.append(("PARALLEL", "", task[m.end():]))
                break
            out.append(("PARALLEL", "", task[m.end():close.start()]))
            pos = close.end()
        else:
            out.append((cm.group("name").upper(), cm.group("arg"), cm.group("body")))
            pos = cm.end()
    return out

# Tools that live in a loadable skill rather than the core tool set. When a
# directive needs one of these and it isn't loaded yet, the fake first calls
# load_skill — exactly what a cooperative model would do.
_REQUIRED_SKILL: dict[str, str] = {
    "run_bash_cmd": "coder",
    "write_file": "coder",
    "read_file": "coder",
    "replace_in_file": "coder",
    # Browser skill tools (reachable via the generic TOOL directive).
    "new_tab": "browser",
    "close_tab": "browser",
    "goto": "browser",
    "go_back": "browser",
    "browse_page": "browser",
    "read_page": "browser",
    "inspect_page": "browser",
    "click": "browser",
    "fill_field": "browser",
    "drag": "browser",
    "scroll_page": "browser",
    "select_option": "browser",
    "press_keys": "browser",
    "press_and_hold": "browser",
    "execute_javascript": "browser",
    "save_page_content": "browser",
    "browser_visual_action": "browser",
}

_COUNTER = {"n": 0}


def _next_id(prefix: str) -> str:
    _COUNTER["n"] += 1
    return f"{prefix}_{_COUNTER['n']}"


def _tool_call(name: str, arguments: dict[str, Any]) -> ToolCall:
    return ToolCall(
        id=_next_id("call"),
        function=ToolCallFunction(name=name, arguments=arguments),
    )


class FakeProvider:
    """A scripted provider that drives the agent loop from a directive protocol."""

    @classmethod
    def from_config(cls, llm_config: LLMConfig) -> "FakeProvider":
        return cls()

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[Callable[..., Any]] | None = None,
        options: dict[str, Any] | None = None,
        think: bool = False,
    ) -> ChatResponse:
        """Return the planned response (used by vision/summarizer call sites)."""
        kind, payload = _plan(messages, tools)
        if kind == "provider_error":
            raise ProviderError(payload[1], retryable=False)
        if kind == "tools":
            return ChatResponse(
                message=ChatMessage(content=None, tool_calls=payload),
                done_reason="tool_calls",
            )
        return ChatResponse(message=ChatMessage(content=payload), done_reason="stop")

    async def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[Callable[..., Any]] | None = None,
        options: dict[str, Any] | None = None,
        think: bool = False,
    ) -> AsyncGenerator[ChatDelta | ChatResponse, None]:
        """Stream content deltas (text replies) then a final ChatResponse."""
        kind, payload = _plan(messages, tools)
        if kind == "provider_error":
            where, message = payload
            if where == "mid":
                # Stream a little before failing, so the UI has a partial
                # in-flight iteration when the provider error lands.
                for chunk in _chunks("Working on it…"):
                    yield ChatDelta(content=chunk)
            raise ProviderError(message, retryable=False)
        if kind == "tools":
            yield ChatResponse(
                message=ChatMessage(content=None, tool_calls=payload),
                done_reason="tool_calls",
            )
            return

        text: str = payload
        slow = bool(_SLOW_RE.search(_latest_task(messages)))
        for chunk in _chunks(text):
            if slow:
                await asyncio.sleep(0.06)
            yield ChatDelta(content=chunk)
        yield ChatResponse(message=ChatMessage(content=text), done_reason="stop")

    async def list_models(self) -> list[ModelInfo]:
        return list(_FAKE_MODELS)

    def invalidate_model_cache(self) -> None:
        """No cache to clear."""


def _chunks(text: str, size: int = 24) -> list[str]:
    if not text:
        return [""]
    return [text[i : i + size] for i in range(0, len(text), size)]


def _latest_task(messages: list[dict[str, Any]]) -> str:
    """Return the most recent user instruction in the history."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content")
            if isinstance(content, str):
                return content
    return ""


def _completed_step_count(messages: list[dict[str, Any]]) -> int:
    """Count completed *logical* tool steps since the latest user instruction.

    load_skill calls are infrastructure the fake injects to make a gated tool
    available; they don't advance the directive sequence, so they're excluded.
    """
    last_user = -1
    for i, msg in enumerate(messages):
        if msg.get("role") == "user":
            last_user = i
    progress = messages[last_user + 1 :] if last_user >= 0 else []
    return sum(
        1 for m in progress
        if m.get("role") == "tool" and m.get("tool_name") != "load_skill"
    )


def _tool_call_from_directive(arg: str, body: str) -> ToolCall:
    """Build a tool call from a TOOL directive's name arg and JSON body."""
    return _tool_call(arg.strip(), json.loads(body) if body.strip() else {})


def _build_rounds(
    directives: list[tuple[str, str, str]],
) -> tuple[list[list[ToolCall]], list[str], tuple[str, str] | None, tuple[int, str] | None]:
    """Group (kind, arg, body) directives into ordered rounds of tool calls,
    plus SAY text and the control directives.

    A plain TOOL is a round of one call; a PARALLEL block is a single round of
    all its inner calls, which the loop runs together; a run of consecutive
    SPAWNs collapses into one round, since a model delegating to several agents
    issues the spawn_agent calls together (the UI groups them into one card).

    Returns (rounds, say_parts, provider_fail, fail_after):
      provider_fail = (where, message) when a PROVIDERFAIL directive is present —
        "mid" fails partway through the stream, "before" fails before any output;
      fail_after = (n_steps, message) when a FAIL directive is present — the
        agent loop raises once it has completed n_steps tool steps.
    """
    rounds: list[list[ToolCall]] = []
    say_parts: list[str] = []
    provider_fail: tuple[str, str] | None = None
    fail_after: tuple[int, str] | None = None
    steps = 0  # tool steps queued so far; a PARALLEL round counts each call
    for kind, arg, body in directives:
        if kind == "SPAWN":
            # arg is "profile" or "profile|NAME"; the optional name sets the
            # sub-agent's UI display name so sibling sub-agents can be told apart.
            spawn_profile, _, spawn_name = arg.strip().partition("|")
            call = _tool_call(
                "spawn_agent",
                {
                    "instructions": body.strip(),
                    "profile": spawn_profile.strip() or _default_profile_id(),
                    "agent_name": spawn_name.strip() or "SUBAGENT",
                },
            )
            # Collapse a run of consecutive spawns into the current round.
            if rounds and all(c.function.name == "spawn_agent" for c in rounds[-1]):
                rounds[-1].append(call)
            else:
                rounds.append([call])
            steps += 1
        elif kind == "PARALLEL":
            calls = [
                _tool_call_from_directive(t.group("pname"), t.group("pbody"))
                for t in _INNER_TOOL_RE.finditer(body)
            ]
            if calls:
                rounds.append(calls)
                steps += len(calls)
        elif kind == "SAY":
            say_parts.append(body)
        elif kind == "PROVIDERFAIL":
            if provider_fail is None:  # first wins
                where = "mid" if arg.strip().lower() == "mid" else "before"
                provider_fail = (where, body.strip() or "provider error")
        elif kind == "FAIL":
            if fail_after is None:  # first FAIL wins
                fail_after = (steps, body.strip() or "fake failure")
        else:  # TOOL
            rounds.append([_tool_call_from_directive(arg, body)])
            steps += 1
    return rounds, say_parts, provider_fail, fail_after


def _plan(
    messages: list[dict[str, Any]],
    tools: list[Callable[..., Any]] | None,
) -> tuple[str, Any]:
    """Plan the next step. Returns ("tools", [ToolCall]) or ("final", text)."""
    task = _latest_task(messages)
    directives = _iter_directives(task)

    # No protocol in the prompt: echo it back verbatim.
    if not directives:
        return "final", task or "OK"

    rounds, say_parts, provider_fail, fail_after = _build_rounds(directives)

    # PROVIDERFAIL makes the provider itself raise (a real ProviderError, e.g. a
    # 429) — surfaced before, or partway through, the stream by the caller.
    if provider_fail is not None:
        return "provider_error", provider_fail

    completed = _completed_step_count(messages)
    # FAIL makes the agent raise once it has completed the tool steps that
    # precede it, driving a genuine error status through the real agent loop
    # (run_turn re-raises → the agent span records status="error").
    if fail_after is not None and completed >= fail_after[0]:
        raise RuntimeError(fail_after[1])

    available = {getattr(t, "__name__", "") for t in (tools or [])}
    # Emit the first round not yet fully completed. A round whose calls need an
    # unloaded skill triggers a load_skill first (load_skill is not counted as a
    # completed step, so we re-enter the same round once it's available).
    seen = 0
    for round_calls in rounds:
        if completed < seen + len(round_calls):
            for call in round_calls:
                skill = _REQUIRED_SKILL.get(call.function.name)
                if skill and call.function.name not in available:
                    return "tools", [_tool_call("load_skill", {"name": skill})]
            return "tools", round_calls[completed - seen:]
        seen += len(round_calls)

    return "final", "\n".join(say_parts) if say_parts else "done"


def _default_profile_id() -> str:
    """Resolve a real, enabled profile id for spawn_agent (lazy import)."""
    from agents import get_default_profile

    return get_default_profile().id
