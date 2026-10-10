"""Cache the stable conversation prefix before transient runtime context."""

from typing import Any


def cache_stable_prefix(messages: list[dict[str, Any]]) -> None:
    """Mark the last converted message before the runtime suffix (always last).

    Used only for APIs supporting Anthropic-style cache_control blocks. The
    converted request belongs to the caller; never mutate conversation events.
    """
    if len(messages) < 2:
        return
    stable = messages[-2]
    content = stable.get("content")
    if isinstance(content, str):
        stable["content"] = [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
    elif isinstance(content, list) and content:
        stable["content"] = [*content[:-1], {**content[-1], "cache_control": {"type": "ephemeral"}}]
