"""Deterministic in-process LLM provider for tests.

This provider lets the whole app run without any real LLM backend. It is
selected by ``get_provider`` when the ``MOCK_LLM`` environment
variable is set, so both ``/api/models`` and the chat tool-loop are served
from canned, deterministic behaviour.

Rather than guess intent from natural language, the fake reads an explicit
**directive protocol** embedded in the user message. A prompt is a sequence
of directives, each delimited by ``<<NAME ...>>`` ... ``<<END>>``:

    <<SAY>>text<<END>>             reply with this text (verbatim, multiline)
    <<BASH>>command<<END>>         run_bash_cmd(cmd=command)
    <<WRITE path>>content<<END>>   write_file(path, content)
    <<SEND>>path<<END>>            send_file(path)
    <<OPEN>>url<<END>>             new_tab(url)
    <<SPAWN profile>>...<<ENDSPAWN>>
        spawn_agent(profile); the body is itself a directive sequence that
        the sub-agent runs. ``profile`` defaults to the default profile when
        omitted. SPAWN uses its own ``<<ENDSPAWN>>`` terminator so its body
        can contain nested ``<<END>>`` directives.

Directives run in the order written: tool directives become tool calls (one
per loop iteration, so e.g. WRITE then SEND never race), and any SAY text is
returned once every tool directive has completed. A prompt with no directives
is echoed back verbatim.

Because the agent loop re-sends the full history on every call, the planner
is stateless: it counts the tool results already in the history to decide
which directive comes next.
"""

from __future__ import annotations

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
    r"|<<(?P<name>SAY|BASH|WRITE|SEND|OPEN)(?P<arg>[^>]*)>>(?P<body>.*?)<<END>>",
    re.IGNORECASE | re.DOTALL,
)

# Tools that live in a loadable skill rather than the core tool set. When a
# directive needs one of these and it isn't loaded yet, the fake first calls
# load_skill — exactly what a cooperative model would do.
_REQUIRED_SKILL: dict[str, str] = {
    "run_bash_cmd": "coder",
    "write_file": "coder",
    "read_file": "coder",
    "replace_in_file": "coder",
    "new_tab": "browser",
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


def _named_tool_call(name: str, arg: str, body: str) -> ToolCall | None:
    """Build the tool call for a single non-SPAWN directive, or None for SAY."""
    name = name.upper()
    arg = arg.strip()
    if name == "BASH":
        return _tool_call("run_bash_cmd", {"cmd": body})
    if name == "WRITE":
        return _tool_call("write_file", {"path": arg, "content": body})
    if name == "SEND":
        return _tool_call("send_file", {"path": body.strip() or arg})
    if name == "OPEN":
        return _tool_call("new_tab", {"url": body.strip() or arg})
    return None  # SAY


def _plan(
    messages: list[dict[str, Any]],
    tools: list[Callable[..., Any]] | None,  # noqa: ARG001 - kept for symmetry
) -> tuple[str, Any]:
    """Plan the next step. Returns ("tools", [ToolCall]) or ("final", text)."""
    task = _latest_task(messages)
    directives = list(_DIRECTIVE_RE.finditer(task))

    # No protocol in the prompt: echo it back verbatim.
    if not directives:
        return "final", task or "OK"

    tool_calls: list[ToolCall] = []
    say_parts: list[str] = []
    for m in directives:
        if m.group("spawn_body") is not None:
            tool_calls.append(_tool_call(
                "spawn_agent",
                {
                    "instructions": m.group("spawn_body").strip(),
                    "profile": m.group("spawn_arg").strip() or _default_profile_id(),
                    "agent_name": "SUBAGENT",
                },
            ))
            continue
        name = m.group("name").upper()
        if name == "SAY":
            say_parts.append(m.group("body"))
            continue
        call = _named_tool_call(name, m.group("arg"), m.group("body"))
        if call is not None:
            tool_calls.append(call)

    completed = _completed_step_count(messages)
    if completed < len(tool_calls):
        # Issue the next directive (one per round to preserve order). If it
        # needs a skill that isn't loaded yet, load that skill first.
        next_call = tool_calls[completed]
        skill = _REQUIRED_SKILL.get(next_call.function.name)
        available = {getattr(t, "__name__", "") for t in (tools or [])}
        if skill and next_call.function.name not in available:
            return "tools", [_tool_call("load_skill", {"name": skill})]
        return "tools", [next_call]

    return "final", "\n".join(say_parts) if say_parts else "done"


def _default_profile_id() -> str:
    """Resolve a real, enabled profile id for spawn_agent (lazy import)."""
    from agents import get_default_profile

    return get_default_profile().id
