"""The server's process-scoped runtime shared by channel and routine adapters."""

from aiohttp import web
from agent_runtime import AgentRuntime

AGENT_RUNTIME_KEY: web.AppKey[AgentRuntime] = web.AppKey("agent_runtime", AgentRuntime)

__all__ = ["AGENT_RUNTIME_KEY"]
