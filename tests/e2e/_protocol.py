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


def say(text: str) -> str:
    """Assistant replies with *text* (verbatim; may be multiline)."""
    return f"<<SAY>>{text}<<END>>"


def bash(cmd: str) -> str:
    """Agent runs *cmd* via run_bash_cmd."""
    return f"<<BASH>>{cmd}<<END>>"


def write_file(path: str, content: str) -> str:
    """Agent writes *content* to *path* via write_file."""
    return f"<<WRITE {path}>>{content}<<END>>"


def send_file(path: str) -> str:
    """Agent sends *path* to the user via send_file."""
    return f"<<SEND>>{path}<<END>>"


def open_url(url: str) -> str:
    """Agent opens *url* via the browser tool (browser skill auto-loaded)."""
    return f"<<OPEN>>{url}<<END>>"


def fail(message: str = "fake failure") -> str:
    """Agent raises after any preceding tool directives, ending with an
    ``error`` status. Use inside a ``spawn`` body to make a sub-agent
    fail, or at the top level to fail the root turn.
    """
    return f"<<FAIL>>{message}<<END>>"


def spawn(body: str, profile: str = "", name: str = "") -> str:
    """Agent spawns a sub-agent.

    *body* is itself a directive sequence the sub-agent runs. *profile*
    defaults to the default profile. *name* sets the sub-agent's display
    name in the UI (defaults to ``SUBAGENT``) — pass it when a test
    needs to tell sibling sub-agents apart in the network view.
    """
    arg = f"{profile}|{name}" if name else profile
    return f"<<SPAWN {arg}>>{body}<<ENDSPAWN>>"
