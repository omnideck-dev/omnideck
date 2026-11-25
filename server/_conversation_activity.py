"""Chat list changes on the app-wide activity stream."""

from __future__ import annotations

from collections.abc import Callable

from conversations import ConversationChange, subscribe_conversation_changes
from server._activity_messages import (
    ActivityMessage, ConversationChangedMessage, ConversationRemovedMessage, ConversationResyncMessage,
)


def conversation_message(change: ConversationChange) -> ActivityMessage:
    """The activity message for a chat's listing after a change."""
    if change.summary is None:
        return ConversationRemovedMessage(type="conversation_removed", conversation_id=change.conversation_id)
    return ConversationChangedMessage(
        type="conversation_changed", conversation=change.summary, archived=change.archived,
    )


class ConversationActivityFeed:
    """Every chat creation, rename, pin, filing, archive, restore and deletion on the activity stream.

    The snapshot carries no chats. It asks the browser to reload its lists, which costs
    one listing per connection instead of sending every chat on every reconnect.
    """

    def subscribe(self, send: Callable[[ActivityMessage], bool]) -> Callable[[], None]:
        def changed(change: ConversationChange) -> None:
            send(conversation_message(change))
        return subscribe_conversation_changes(changed)

    def snapshot(self) -> ActivityMessage | None:
        return ConversationResyncMessage(type="conversation_resync")
