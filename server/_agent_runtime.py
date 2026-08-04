"""Compose and expose the server's process-scoped agent runtime."""

from aiohttp import web

from agent_runtime import ActiveRunManager, AgentRunner
from sdk.context import ConversationHistory
from server._conversation_cache import get_or_create_conversation

ACTIVE_RUN_MANAGER_KEY: web.AppKey[ActiveRunManager] = web.AppKey(
    "active_run_manager",
    ActiveRunManager,
)


async def _load_conversation(conversation_id: str) -> ConversationHistory:
    return await get_or_create_conversation(conversation_id)


def build_agent_runner() -> AgentRunner:
    """Build the channel-neutral runner with application persistence attached."""
    return AgentRunner(_load_conversation)


__all__ = ["ACTIVE_RUN_MANAGER_KEY", "build_agent_runner"]
