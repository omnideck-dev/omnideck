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


def call_tool(name: str, **args: object) -> str:
    """Agent invokes tool *name* with keyword *args* (a generic escape hatch).

    Use for any agent tool that has no dedicated directive, e.g.
    ``call_tool("close_tab", tab=2)`` or ``call_tool("goto", url="...", tab=1)``.
    Skill-gated tools (e.g. browser tools) are loaded automatically before use.
    """
    return f"<<TOOL {name}>>{json.dumps(args)}<<END>>"


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


def spawn(body: str, profile: str = "") -> str:
    """Agent spawns a sub-agent (profile defaults to the default profile).

    *body* is itself a directive sequence the sub-agent runs.
    """
    return f"<<SPAWN {profile}>>{body}<<ENDSPAWN>>"
