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
    <<SPAWN profile>>...<<ENDSPAWN>>
        spawn_agent(profile); the body is itself a directive sequence that
        the sub-agent runs. ``profile`` defaults to the default profile when
        omitted. SPAWN uses its own ``<<ENDSPAWN>>`` terminator so its body
        can contain nested ``<<END>>`` directives.
    <<PARALLEL>><<TOOL ...>>...<<END>>...<<ENDPARALLEL>>
        emit the contained TOOL directives in a single response so the loop
        runs them concurrently (when parallel tool execution is enabled),
        letting tests exercise real tool-call races.

Directives run in the order written: a plain tool directive is one tool call
per loop iteration (so e.g. WRITE then SEND never race), a PARALLEL block is
one batch run together, and any SAY text is returned once every tool directive
has completed. A prompt with no directives is echoed back verbatim.

Because the agent loop re-sends the full history on every call, the planner
is stateless: it counts the tool results already in the history to decide
which directive comes next.
"""

from __future__ import annotations

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

# One regex matches any directive, in order. SPAWN has its own terminator so
# its body may contain nested <<END>> directives for the sub-agent to run.
_DIRECTIVE_RE = re.compile(
    r"<<SPAWN(?P<spawn_arg>[^>]*)>>(?P<spawn_body>.*?)<<ENDSPAWN>>"
    r"|<<PARALLEL>>(?P<par_body>.*?)<<ENDPARALLEL>>"
    r"|<<(?P<name>SAY|TOOL)(?P<arg>[^>]*)>>(?P<body>.*?)<<END>>",
    re.IGNORECASE | re.DOTALL,
)

# Inner TOOL directives within a PARALLEL block. The block's calls are emitted
# in one response so the agent loop runs them concurrently (when parallel tool
# execution is enabled), letting tests exercise real tool-call races.
_INNER_TOOL_RE = re.compile(r"<<TOOL(?P<pname>[^>]*)>>(?P<pbody>.*?)<<END>>", re.IGNORECASE | re.DOTALL)

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
        if kind == "tools":
            yield ChatResponse(
                message=ChatMessage(content=None, tool_calls=payload),
                done_reason="tool_calls",
            )
            return

        text: str = payload
        for chunk in _chunks(text):
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
    directives: list[re.Match[str]],
) -> tuple[list[list[ToolCall]], list[str]]:
    """Group directives into ordered rounds of tool calls, plus any SAY text.

    A plain TOOL or SPAWN is a round of one call; a PARALLEL block is a single
    round of all its inner calls, which the loop then runs together.
    """
    rounds: list[list[ToolCall]] = []
    say_parts: list[str] = []
    for m in directives:
        if m.group("spawn_body") is not None:
            rounds.append([_tool_call(
                "spawn_agent",
                {
                    "instructions": m.group("spawn_body").strip(),
                    "profile": m.group("spawn_arg").strip() or _default_profile_id(),
                    "agent_name": "SUBAGENT",
                },
            )])
        elif m.group("par_body") is not None:
            calls = [
                _tool_call_from_directive(t.group("pname"), t.group("pbody"))
                for t in _INNER_TOOL_RE.finditer(m.group("par_body"))
            ]
            if calls:
                rounds.append(calls)
        elif m.group("name").upper() == "SAY":
            say_parts.append(m.group("body"))
        else:  # TOOL
            rounds.append([_tool_call_from_directive(m.group("arg"), m.group("body"))])
    return rounds, say_parts


def _plan(
    messages: list[dict[str, Any]],
    tools: list[Callable[..., Any]] | None,
) -> tuple[str, Any]:
    """Plan the next step. Returns ("tools", [ToolCall]) or ("final", text)."""
    task = _latest_task(messages)
    directives = list(_DIRECTIVE_RE.finditer(task))

    # No protocol in the prompt: echo it back verbatim.
    if not directives:
        return "final", task or "OK"

    rounds, say_parts = _build_rounds(directives)
    completed = _completed_step_count(messages)
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
