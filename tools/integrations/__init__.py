"""Agent-visible tools backed by the integrations subsystem.

Each tool is included only when a running integration connection grants its
canonical operation in the supplied application-owned connection snapshot.
Tools are bound to that connection; native tools expose no routing argument.
"""

from tools.integrations._tool_resolution import connection_tools

__all__ = [
    "connection_tools",
]
