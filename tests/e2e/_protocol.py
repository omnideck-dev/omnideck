"""Directive-protocol helpers for driving the FakeProvider in e2e tests.

The e2e suite runs the app with ``MOCK_LLM=1``, which swaps the real
LLM for an in-process fake. The fake reads these
directives out of the user message and performs the matching deterministic
actions — calling the same real tools a model would — so chat-driven tests are
fast and need no model.

Compose directives by concatenating them; tool directives run in order, then
any ``say`` text is returned as the final assistant reply. Skill-gated tools
(bash/file/browser) are loaded automatically by the fake before use.

Example::

    chat.send(write_file("notes.txt", "hello") + send_file("notes.txt"))
    chat.send(say("done"))
"""

from __future__ import annotations

import json


def say(text: str) -> str:
    """Assistant replies with *text* (verbatim; may be multiline)."""
    return f"<<SAY>>{text}<<END>>"


def model_script(*responses: dict) -> str:
    """Script model messages, including thinking/content before real tool calls.

    Each response uses ChatMessage fields. Non-final responses must call a tool
    so the real SDK loop continues. No runtime event or tool result is supplied.
    """
    body = json.dumps(responses).replace("<", "\\u003c")
    return f"<<MODEL>>{body}<<END>>"


def model_tool(name: str, **arguments: object) -> dict:
    """One model-requested tool call for a model_script response."""
    return {"function": {"name": name, "arguments": arguments}}


def call_tool(tool_name: str, **args: object) -> str:
    """Agent invokes *tool_name* with keyword *args* (a generic escape hatch).

    Use for any agent tool that has no dedicated directive, e.g.
    ``call_tool("close_tab", tab=2)`` or ``call_tool("goto", url="...", tab=1)``.
    Skill-gated tools (e.g. browser tools) are loaded automatically before use.
    """
    # A tool argument can itself contain directives, as routine task
    # instructions do. Escape '<' inside the JSON body so the outer directive
    # parser cannot mistake a nested <<END>> for this call's terminator. JSON
    # decoding restores the original text before the real tool is invoked.
    body = json.dumps(args).replace("<", "\\u003c")
    return f"<<TOOL {tool_name}>>{body}<<END>>"


def bash(cmd: str) -> str:
    """Agent runs *cmd* via run_bash_cmd."""
    return call_tool("run_bash_cmd", cmd=cmd)


def write_file(path: str, content: str) -> str:
    """Agent writes *content* to *path* via write_file."""
    return call_tool("write_file", path=path, content=content)


def send_file(path: str) -> str:
    """Agent sends *path* to the user via send_file."""
    return call_tool("send_file", path=path)


def open_url(url: str) -> str:
    """Agent opens *url* in a new browser tab (browser skill auto-loaded)."""
    return call_tool("new_tab", url=url)


def parallel(*directives: str) -> str:
    """Agent issues *directives* (each a TOOL directive) as one concurrent batch.

    The fake emits them in a single response, so with parallel tool execution
    enabled the loop runs them at once — e.g. ``parallel(open_url(a),
    open_url(b))`` opens both tabs concurrently, racing as a real model would.
    """
    return "<<PARALLEL>>" + "".join(directives) + "<<ENDPARALLEL>>"


def fail(message: str = "fake failure") -> str:
    """Agent raises after any preceding tool directives, ending with an
    ``error`` status. Use inside a ``spawn`` body to make a sub-agent
    fail, or at the top level to fail the root turn.
    """
    return f"<<FAIL>>{message}<<END>>"


def slow() -> str:
    """Marker: the assistant's text reply streams with a small per-chunk
    delay, opening a window to interact mid-stream (e.g. click Stop).
    Compose outside other directives: ``slow() + say(long_text)``.
    """
    return "<<SLOW>>"


def provider_fail(message: str = "provider error", *, mid: bool = False) -> str:
    """The provider itself raises, modeling a real ProviderError (e.g. a 429).

    With ``mid=False`` (default) it fails before any output streams — the
    turn never produces content. With ``mid=True`` it streams a little first,
    then fails partway through, leaving a partial in-flight iteration.
    """
    return f"<<PROVIDERFAIL{' mid' if mid else ''}>>{message}<<END>>"


def spawn(body: str, profile: str = "", name: str = "") -> str:
    """Agent spawns a sub-agent.

    *body* is itself a directive sequence the sub-agent runs. *profile*
    defaults to the default profile. *name* sets the sub-agent's display
    name in the UI (defaults to ``SUBAGENT``) — pass it when a test
    needs to tell sibling sub-agents apart in the network view.
    """
    arg = f"{profile}|{name}" if name else profile
    return f"<<SPAWN {arg}>>{body}<<ENDSPAWN>>"
