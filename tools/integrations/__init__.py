"""Agent-visible tools backed by the integrations subsystem.

Each tool is included only when a running integration connection grants its
canonical operation in the supplied application-owned connection snapshot.
The model-facing ``integration_id`` argument retains its existing name but
identifies a connection, not a catalog preset.
"""

from tools.integrations._tool_resolution import OperationTools, integration_tools_by_category

__all__ = [
    "OperationTools",
    "integration_tools_by_category",
]
