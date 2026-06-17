"""Public exports for the events package.

This package provides:
- Event models (AgentEvent, ContentPayload, ToolCallPayload, etc.)
- Context utilities for publishing events without plumbing the active
    event sink through every call site. Low-level helpers like
    ``publish_event`` and ``agent_span`` are available for emission and
    attribution inside a turn scope.

Turn lifecycle management (``turn_scope``, stop signaling, nudge queues) lives
in ``sdk.turn``.
"""

from ._cleanup import register_agent_span_exit_hook
from ._context import (
    EventSink,
    agent_span,
    get_current_agent_id,
    get_current_agent_name,
    get_current_depth,
    get_current_event_sink,
    publish_event,
    reset_current_event_sink,
    set_current_event_sink,
)
from ._models import (
    AgentCompletedPayload,
    AgentEvent,
    AgentEventPayload,
    AgentStartedPayload,
    AudioPlaybackPayload,
    BrowserScreenshotPayload,
    CompactionPayload,
    CompactionScope,
    CompactionStats,
    ContentPayload,
    ContextUsagePayload,
    DesktopActivePayload,
    ErrorPayload,
    FileOutputPayload,
    GenerationPreviewPayload,
    IterationPayload,
    IterationToolCall,
    SpawnRequestedPayload,
    TerminalOutputPayload,
    ToolCallPayload,
    ToolCreatedPayload,
    ToolResultPayload,
    TurnEndPayload,
    UserAttachment,
    UserMessagePayload,
)

__all__ = [
    "register_agent_span_exit_hook",
    "AgentCompletedPayload",
    "AgentEvent",
    "AgentEventPayload",
    "AgentStartedPayload",
    "AudioPlaybackPayload",
    "BrowserScreenshotPayload",
    "CompactionPayload",
    "CompactionScope",
    "CompactionStats",
    "ContentPayload",
    "ContextUsagePayload",
    "DesktopActivePayload",
    "ErrorPayload",
    "EventSink",
    "FileOutputPayload",
    "GenerationPreviewPayload",
    "IterationPayload",
    "IterationToolCall",
    "SpawnRequestedPayload",
    "TerminalOutputPayload",
    "ToolCallPayload",
    "ToolCreatedPayload",
    "ToolResultPayload",
    "TurnEndPayload",
    "UserAttachment",
    "UserMessagePayload",
    "agent_span",
    "get_current_agent_id",
    "get_current_agent_name",
    "get_current_depth",
    "get_current_event_sink",
    "publish_event",
    "reset_current_event_sink",
    "set_current_event_sink",
]
