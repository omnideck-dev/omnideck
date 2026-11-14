"""Cache an append-only conversation at its latest message."""

from typing import Any


def cache_conversation(messages: list[dict[str, Any]]) -> None:
    """Mark the final converted message as an explicit cache boundary.

    Used only for APIs supporting Anthropic-style cache_control blocks. The
    converted request belongs to the caller; never mutate conversation events.
    """
    if not messages:
        return
    for message in messages:
        # Anthropic rejects empty text blocks, so empty text stays a plain string.
        if isinstance(message.get("content"), str) and message["content"]:
            message["content"] = [{"type": "text", "text": message["content"]}]
    stable = next((message for message in reversed(messages)
                   if isinstance(message.get("content"), list) and message["content"]), None)
    if stable is not None:
        content = stable["content"]
        stable["content"] = [*content[:-1], {**content[-1], "cache_control": {"type": "ephemeral"}}]
