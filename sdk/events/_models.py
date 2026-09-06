"""Event models: the typed records that make up a conversation's event log.

Agents emit AgentEvents while handling a turn. These are not transient UI
notifications — they are the persisted, append-only record a conversation is
built from, and the LLM-facing history is derived from them. The schema uses a
discriminated union on the ``type`` field so new event types can be added
without breaking existing consumers.

Design notes:
- Each AgentEvent carries a stable ``id`` and serializes via ``to_flat_dict``
  to the one-line-JSON shape written to the append-only events log.
- Binary payloads are base64-encoded strings paired with a content type.
- Event payloads use a discriminator field named "type".
- AgentEvent is a thin envelope: metadata + a single typed payload.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ContentPayload(BaseModel):
    """LLM-generated text content (natural language and/or chain-of-thought).

    Attributes:
        type: Discriminator; always "content".
        content: Natural-language content produced by the model, if any.
        thinking: Chain-of-thought or rationale text, if available.
        delta: When True, content/thinking are incremental token deltas to
            append. When None, they are complete chunks.
    """

    type: Literal["content"]
    content: str | None = None
    thinking: str | None = None
    delta: bool | None = None


class TurnEndPayload(BaseModel):
    """Signals the end of a turn — the root agent has finished responding.

    Attributes:
        type: Discriminator; always "turn_end".
    """

    type: Literal["turn_end"]


class ToolCallPayload(BaseModel):
    """Metadata for tool invocation notifications.

    Attributes:
        type: Discriminator; always "tool_call".
        name: The name of the tool being invoked.
        arguments: Tool arguments, stringified and length-capped for
            display. None when the call carried no arguments.
    """

    type: Literal["tool_call"]
    name: str
    arguments: dict[str, str] | None = None


class SpawnRequestedPayload(BaseModel):
    """Emitted by the spawn_agent tool when it begins spawning a sub-agent.

    Carries a correlation id that the matching AgentStartedPayload also
    carries, letting the UI anchor a card to this request and attach the
    child agent to it. Always emitted from the parent agent's context,
    so the publish layer fills in the parent agent_id.

    Attributes:
        type: Discriminator; always "spawn_requested".
        correlation_id: Id shared with the AgentStartedPayload of the
            sub-agent this request will spawn.
    """

    type: Literal["spawn_requested"]
    correlation_id: str


class BrowserScreenshotPayload(BaseModel):
    """Metadata for browser screenshot events.

    Attributes:
        type: Discriminator; always "browser_screenshot".
        url: The current URL of the browser page.
        title: The page title.
        screenshot: Base64-encoded PNG screenshot of the viewport, or None for
            a reconcile-only event (e.g. after a tab closes, which produces no
            screenshot) that carries just the open-tab set.
        tab_id: Stable tab ID this screenshot belongs to.  The UI uses
            it to route screenshots into per-tab thumbnail slots. None on a
            reconcile-only event.
        open_tab_ids: Stable IDs of all currently-open tabs at capture time.
            The UI reconciles its thumbnail set against this so tabs that have
            since closed are pruned rather than lingering as stale thumbnails.
    """

    type: Literal["browser_screenshot"]
    url: str
    title: str
    screenshot: str | None = None  # base64 PNG; None = reconcile-only event
    tab_id: int | None = None
    open_tab_ids: list[int] | None = None


class FileOutputPayload(BaseModel):
    """Metadata for file output events.

    Attributes:
        type: Discriminator; always "file_output".
        filename: The name of the file (basename for display/download).
        content_type: The MIME type of the file (e.g., "text/csv", "image/png").
        content: Base64-encoded file content (legacy, prefer ``path``).
        path: Absolute container path served by the file route.
    """

    type: Literal["file_output"]
    filename: str
    content_type: str
    content: str | None = None
    path: str | None = None
    tool_call_id: str | None = None


class ToolCreatedPayload(BaseModel):
    """Emitted when a new custom tool is successfully created.

    Attributes:
        type: Discriminator; always "tool_created".
        name: The name of the newly created tool.
    """

    type: Literal["tool_created"]
    name: str


class AudioPlaybackPayload(BaseModel):
    """Emitted when the agent wants to play audio directly in the browser.

    Attributes:
        type: Discriminator; always "audio_playback".
        content_type: MIME type of the audio (e.g. "audio/mpeg").
        content: Base64-encoded audio content.
    """

    type: Literal["audio_playback"]
    content_type: str
    content: str  # base64 encoded


class TerminalOutputPayload(BaseModel):
    """Emitted when a bash command starts or completes in the virtual computer.

    Two events are published per command: one with ``status="running"`` before
    execution begins (carrying only the command text), and one with
    ``status="completed"`` after execution finishes (carrying output and exit
    code).  Both share the same ``cmd_id`` so the frontend can correlate them.

    Attributes:
        type: Discriminator; always "terminal_output".
        cmd_id: Unique identifier linking the running/completed pair.
        cmd: The command that was executed.
        status: Either "running" or "completed".
        stdout: Standard output text, if any.
        stderr: Standard error text, if any.
        exit_code: Exit code of the command, if available.
    """

    type: Literal["terminal_output"]
    cmd_id: str
    cmd: str
    status: Literal["running", "streaming", "completed"] = "completed"
    stdout: str | None = None
    stderr: str | None = None
    exit_code: int | None = None


class DesktopActivePayload(BaseModel):
    """Emitted when the desktop environment starts to signal the UI.

    Attributes:
        type: Discriminator; always "desktop_active".
        resolution: Desktop resolution string (e.g. "1280x720").
    """

    type: Literal["desktop_active"]
    resolution: str


class ContextUsagePayload(BaseModel):
    """Emitted after each LLM call with current context window usage.

    Attributes:
        type: Discriminator; always "context_usage".
        context_used: Prompt + completion tokens consumed on the last call.
        context_limit: The model's context window size.
        fill_ratio: Fraction of the context window consumed (0.0-1.0+).
        compaction_threshold: Fill ratio at which compaction fires for the
            agent active on this call. Per-profile and configurable, so it
            is emitted with every event rather than assumed constant.
    """

    type: Literal["context_usage"]
    context_used: int
    context_limit: int
    fill_ratio: float
    compaction_threshold: float = 0.75
    iteration: int | None = None
    max_iterations: int | None = None


class GenerationPreviewPayload(BaseModel):
    """Emitted during image/video generation to stream progress and previews.

    Multiple events share the same ``gen_id`` to track a single generation.
    For images, ``preview`` contains a TAESD-decoded JPEG at each step.
    For video, ``preview`` is sent periodically (first frame only).
    On completion, ``output`` contains the base64-encoded final file.

    Attributes:
        type: Discriminator; always "generation_preview".
        gen_id: Unique identifier correlating progress events.
        media_type: Either "image" or "video".
        status: Current generation phase.
        step: Current inference step number.
        total_steps: Total inference steps.
        preview: Base64-encoded JPEG preview image.
        message: Human-readable status text.
        output: Base64-encoded final file on completion.
        output_content_type: MIME type of the final output.
    """

    type: Literal["generation_preview"]
    gen_id: str
    media_type: str
    status: Literal["loading", "generating", "complete", "failed"]
    step: int | None = None
    total_steps: int | None = None
    preview: str | None = None
    message: str | None = None
    output: str | None = None
    output_content_type: str | None = None
    output_path: str | None = None


class AgentStartedPayload(BaseModel):
    """Emitted when an agent begins execution.

    Attributes:
        type: Discriminator; always "agent_started".
        agent_id: Hierarchical context id for this agent instance.
        agent_name: Human-readable agent name.
        parent_agent_id: Context id of the parent agent, or None for root.
        instruction: The instruction or user message this agent was given.
        profile_name: Name of the agent profile used, if any.
        correlation_id: For sub-agents spawned via spawn_agent, the id
            shared with the originating SpawnRequestedPayload. None for
            root agents.
    """

    type: Literal["agent_started"]
    agent_id: str
    agent_name: str
    parent_agent_id: str | None = None
    instruction: str | None = None
    profile_name: str | None = None
    correlation_id: str | None = None


class AgentCompletedPayload(BaseModel):
    """Emitted when an agent finishes execution.

    Attributes:
        type: Discriminator; always "agent_completed".
        agent_id: Hierarchical context id for this agent instance.
        agent_name: Human-readable agent name.
        status: How the agent finished — success, error, or stopped.
    """

    type: Literal["agent_completed"]
    agent_id: str
    agent_name: str
    status: Literal["success", "error", "stopped"]


class ErrorPayload(BaseModel):
    """A turn failed and the failure should be shown to the user.

    Emitted when an agent's turn raises (e.g. a provider error). Carries
    a human-readable message — the cleaned provider message when available
    — so the UI can show why the turn ended instead of failing silently.

    Attributes:
        type: Discriminator; always "error".
        message: Human-readable failure message for display.
        retryable: True when the underlying failure is transient (the
            provider flagged it retryable), so the UI can hint that
            trying again may succeed.
    """

    type: Literal["error"]
    message: str
    retryable: bool = False


class UserAttachment(BaseModel):
    """A single file attachment carried by a user message.

    Attributes:
        filename: Display name (basename) of the attached file.
        content_type: MIME type (e.g. "image/png", "text/csv").
        path: Absolute path under the virtual computer where the file
            was written before the LLM ran.
    """

    filename: str
    content_type: str
    path: str


class UserMessagePayload(BaseModel):
    """User-authored input to an agent — the prompt that opens a turn,
    or a nudge injected mid-turn into a running agent (root or sub-agent).

    Attributes:
        type: Discriminator; always "user_message".
        content: The user-authored text.
        attachments: Files uploaded with the message, materialized on
            the virtual computer before the LLM ran.
        is_nudge: False for the turn-opening prompt; True for queued
            user input that landed between iterations of an already-
            running turn.
    """

    type: Literal["user_message"]
    content: str
    attachments: list[UserAttachment] = Field(default_factory=list)
    is_nudge: bool = False


class IterationToolCall(BaseModel):
    """A single tool call requested by the model on one iteration.

    Attributes:
        id: Provider-issued tool call id. Some providers omit this on
            legacy payloads, so it is optional.
        name: Tool name as the model invoked it.
        arguments: Decoded JSON arguments object. Providers vary
            between dict and stringified JSON; this carries the
            normalized dict form.
    """

    id: str | None = None
    name: str
    arguments: dict | None = None


class IterationPayload(BaseModel):
    """One LLM iteration within a turn — thinking, content, and any
    tool calls the model requested, bundled into a single event.

    Attributes:
        type: Discriminator; always "iteration".
        iteration_index: 0-based index within the current turn.
        thinking: Chain-of-thought text emitted on this iteration.
        content: Natural-language content emitted on this iteration.
        tool_calls: Tool calls the model requested. Empty when the
            iteration produced only content.
        stopped: True when this iteration is partial output captured
            because the turn was interrupted mid-stream (user stop or a
            failure) — the content is whatever streamed before the
            interruption, not a complete iteration.
    """

    type: Literal["iteration"]
    iteration_index: int
    thinking: str | None = None
    content: str | None = None
    tool_calls: list[IterationToolCall] = Field(default_factory=list)
    stopped: bool = False
    # Provider-reported input + output for this call. None for old events,
    # interrupted calls, or providers that did not report usage.
    total_tokens: int | None = Field(default=None, ge=0)


class ToolResultPayload(BaseModel):
    """The result returned by a tool the model invoked.

    Attributes:
        type: Discriminator; always "tool_result".
        tool_call_id: Id of the IterationToolCall this result answers.
        tool_name: Name of the tool that produced the result.
        content: The tool's textual return value.
    """

    type: Literal["tool_result"]
    tool_call_id: str | None = None
    tool_name: str
    content: str


class CompactionScope(BaseModel):
    """Counts of what the compaction summarized."""

    user_messages: int = 0
    iterations: int = 0
    tool_results: int = 0


class CompactionStats(BaseModel):
    """Presentation stats for the compaction chip UI, computed at
    compaction time so consumers don't have to walk the event log.

    All fields are optional — strategies may omit them on platforms or
    code paths where the measurements aren't available.

    Attributes:
        context_before: Token count that triggered the compaction
            (the agent's working context size at trigger time).
        context_after: Estimated token count after compaction —
            ``context_before`` minus the chars the summarizer replaced,
            plus the summary's own size. An estimate; the next iteration
            measures the real number.
        context_limit: The agent's profile context window in tokens.
        saved_tokens: Approximate tokens removed by compaction.
        saved_ratio: ``saved_tokens / context_before``.
        spanned_seconds: Wall time between the first and last event in
            the compacted range.
        scope: Counts of what was compacted (user messages, iterations,
            tool results).
        summary_chars / summary_tokens / summary_lines: Size of the
            summary text the compaction produced.
        model: Summarizer model used for this compaction.
        input_char_count: Characters fed into the summarizer.
        elapsed_seconds: Wall time for the summarization call.
    """

    context_before: int | None = None
    context_after: int | None = None
    context_limit: int | None = None
    saved_tokens: int | None = None
    saved_ratio: float | None = None
    spanned_seconds: float | None = None
    scope: CompactionScope = Field(default_factory=CompactionScope)
    summary_chars: int = 0
    summary_tokens: int = 0
    summary_lines: int = 0
    model: str | None = None
    input_char_count: int | None = None
    elapsed_seconds: float | None = None


class CompactionPayload(BaseModel):
    """Marks a context compaction. The latest compaction in an agent's
    event log defines its LLM view: pin (optionally overridden) +
    summary marker + events from kept_from_id onward.

    Older compactions remain in the log for audit but do not affect
    history reconstruction.

    Attributes:
        type: Discriminator; always "compaction".
        kept_from_id: Inclusive lower bound of events that survive
            into the post-compaction LLM view.
        kept_to_id: Inclusive upper bound — the last event present in
            the log at the moment compaction fired.
        summary_text: The summary produced by the summarizer.
        user_intent_summary: If set, replaces the first user message's
            content with this consolidated intent summary when
            rebuilding the LLM view. Produced by the summarizer when
            the conversation contains multiple user messages whose
            intents may have shifted.
        stats: Presentation and forensic stats computed at compaction
            time for the UI chip panel. Optional — older compaction
            events emitted before this field existed leave it unset and
            the UI falls back to deriving from the event log.
    """

    type: Literal["compaction"]
    kept_from_id: str
    kept_to_id: str
    summary_text: str
    user_intent_summary: str | None = None
    stats: CompactionStats | None = None


AgentEventPayload = Annotated[
    ContentPayload
    | TurnEndPayload
    | ToolCallPayload
    | BrowserScreenshotPayload
    | FileOutputPayload
    | ToolCreatedPayload
    | AudioPlaybackPayload
    | TerminalOutputPayload
    | GenerationPreviewPayload
    | ContextUsagePayload
    | DesktopActivePayload
    | AgentStartedPayload
    | AgentCompletedPayload
    | SpawnRequestedPayload
    | UserMessagePayload
    | IterationPayload
    | ToolResultPayload
    | CompactionPayload
    | ErrorPayload,
    Field(discriminator="type"),
]


class AgentEvent(BaseModel):
    """Top-level event envelope emitted during a turn.

    Carries a single typed payload plus shared metadata for attribution
    and ordering.

    Attributes:
        payload: The typed event payload (discriminated on ``type``).
        id: Stable identifier assigned at construction. Used as the
            event's primary key in the persisted log and as the
            referent for compaction's kept_from_id / kept_to_id.
        timestamp: UTC timestamp when the event was created.
        agent_name: Human-readable agent name for attribution.
        agent_id: Hierarchical context id of the emitting agent.
        depth: Nesting depth (0 = root agent, 1+ = sub-agents).
    """

    payload: AgentEventPayload
    id: str = Field(default_factory=lambda: f"evt_{uuid.uuid4().hex}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    agent_name: str | None = None
    agent_id: str | None = None
    depth: int | None = None

    def to_flat_dict(self, conversation_id: str) -> dict:
        """Render the event as the flat dict shape persisted to events.jsonl.

        Envelope fields and payload fields are merged into a single dict
        keyed by attribute name; the payload's ``type`` becomes the
        top-level discriminator.
        """
        flat: dict = {
            "id": self.id,
            "type": self.payload.type,
            "timestamp": self.timestamp.isoformat(),
            "conversation_id": conversation_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "depth": self.depth,
        }
        flat.update(self.payload.model_dump(exclude={"type"}))
        return flat


__all__ = [
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
]
