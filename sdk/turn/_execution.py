"""Tool loop utilities for executing chat-based LLM interactions with tool calls."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from config import ParallelConfig

from agents.types import Agent
from sdk.context import ConversationHistory
from sdk.events import (
    AgentEvent,
    ContentPayload,
    ErrorPayload,
    IterationPayload,
    IterationToolCall,
    ToolResultPayload,
    publish_event,
)
from sdk.providers import ChatDelta, ChatResponse, ProviderError, ToolCall, get_provider
from sdk.agent_state import _active_agent_state
from sdk.tools import _execute_tool_call

from ._turn import StopRequestedError, check_stop

def _get_parallel_config() -> ParallelConfig:
    """Lazy-load parallel config to avoid circular imports at module level."""
    from config import load_config

    return load_config().parallel


class ToolLoopError(Exception):
    """Custom exception for errors in the tool loop."""


logger = logging.getLogger(__name__)


def _publish_iteration(
    iteration_index: int,
    *,
    content: str | None,
    thinking: str | None,
    tool_calls: list[IterationToolCall] | None = None,
    stopped: bool = False,
) -> None:
    """Publish an iteration event. Logs but never raises on failure."""
    try:
        publish_event(
            AgentEvent(
                payload=IterationPayload(
                    type="iteration",
                    iteration_index=iteration_index,
                    thinking=thinking,
                    content=content,
                    tool_calls=tool_calls or [],
                    stopped=stopped,
                )
            )
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to publish iteration event")


def _persist_partial(
    content_parts: list[str],
    thinking_parts: list[str],
    iteration: int,
) -> str | None:
    """Persist streamed-but-unpublished output as a truncated iteration event.

    Called when a turn unwinds (user stop or failure) so whatever the model
    already streamed survives into the event log instead of vanishing.
    Returns the partial content, or None when nothing had streamed.
    """
    partial_content = "".join(content_parts) or None
    partial_thinking = "".join(thinking_parts) or None
    if partial_content is None and partial_thinking is None:
        return None
    _publish_iteration(
        iteration - 1,
        content=partial_content,
        thinking=partial_thinking,
        stopped=True,
    )
    return partial_content


async def _stream_chat_with_retries(
    provider: Any,
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[Callable[..., Any]],
    options: dict[str, Any] | None = None,
    think: bool = False,
    retries: int = 2,
) -> AsyncGenerator[ChatDelta | ChatResponse, None]:
    """Yield ChatDelta tokens, then the final ChatResponse. Retries on failure.

    If a stream fails mid-way after emitting deltas, retrying would cause
    content duplication. On retry, fall back to non-streaming chat() to
    yield a single complete ChatResponse instead.
    """
    attempt = 0
    total_attempts = 1 + max(0, retries)
    while attempt < total_attempts:
        try:
            if attempt == 0:
                async for chunk in provider.chat_stream(
                    model=model,
                    messages=messages,
                    options=options,
                    tools=tools,
                    think=think,
                ):
                    yield chunk
            else:
                # Retry with non-streaming to avoid content duplication
                yield await provider.chat(
                    model=model,
                    messages=messages,
                    options=options,
                    tools=tools,
                    think=think,
                )
            return
        except ProviderError as exc:
            attempt += 1
            if not exc.retryable:
                logger.error(
                    "provider.chat_stream failed (non-retryable): %s | model=%s",
                    exc,
                    model,
                )
                raise
            delay = min(2**attempt, 8)
            logger.warning(
                "provider.chat_stream failed (attempt %s/%s, retryable, backoff %ds): %s | model=%s",
                attempt,
                total_attempts,
                delay,
                exc,
                model,
            )
            if attempt >= total_attempts:
                raise
            await asyncio.sleep(delay)
        except Exception as exc:
            logger.error(
                "provider.chat_stream failed (unexpected): %s | model=%s",
                exc,
                model,
            )
            raise
    msg = "Failed to get chat response after retries."
    raise ToolLoopError(msg)


async def _run_tool_with_hooks(
    tool_call: Any,
    tools: list[Callable[..., Any]],
    hooks: list[Any],
) -> None:
    """Execute a single tool call with before/after hooks.

    Publishes a ``ToolResultPayload`` for the call. The result also flows
    into the history view through that event — there is no return value.
    """
    tool_name = tool_call.function.name
    tool_arguments = tool_call.function.arguments

    intercepted = None
    for hook in hooks:
        fn = getattr(hook, "before_tool", None)
        if fn:
            intercepted = fn(tool_name, tool_arguments)
            if intercepted is not None:
                break

    if intercepted is not None:
        tool_result = intercepted
    else:
        tool_result = await _execute_tool_call(tool_name, tool_arguments, tools)

    for hook in hooks:
        fn = getattr(hook, "after_tool", None)
        if fn:
            tool_result = fn(tool_name, tool_arguments, tool_result)

    try:
        publish_event(
            AgentEvent(
                payload=ToolResultPayload(
                    type="tool_result",
                    tool_call_id=tool_call.id,
                    tool_name=tool_name,
                    content=str(tool_result) if tool_result is not None else "",
                )
            )
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to publish tool_result event")


async def run_turn(
    history: ConversationHistory,
    agent: Agent,
    *,
    hooks: list[Any] | None = None,
) -> str | None:
    """Executes a single turn with the LLM, handling tool calls.

    Streaming is handled via publish_event; this function drives the loop
    and mutates *history* in place.

    Args:
        history: The conversation history to read from and append to.
        agent: The agent providing model, tools, options, and think flag.
        hooks: Pluggable hooks invoked at six phases of the turn.

    Returns:
        The final assistant message content, or None if no content was produced.

    Raises:
        ToolLoopError: If an unexpected error occurs in the tool loop.
    """
    provider = get_provider(agent.provider)
    agent_state = _active_agent_state.get()
    if agent_state is None:
        raise ToolLoopError("run_turn called outside an agent_span (no active AgentState)")
    if hooks is None:
        hooks = []

    for hook in hooks:
        fn = getattr(hook, "on_turn_start", None)
        if fn:
            fn(agent.name)

    parallel_cfg = _get_parallel_config()
    # Tracks the latest assistant content for the successful run_turn return
    # value and the on_turn_end hook payload. Persistence reads history, not
    # this variable.
    final_content: str | None = None
    iteration = 0
    try:
        while True:
            iteration += 1
            logger.debug("Tool loop iteration %d for agent '%s'", iteration, agent.name)

            # Accumulates this iteration's streamed output so the unwind
            # handlers below can persist it if the turn is interrupted.
            # Reset per iteration and cleared once the full iteration event
            # publishes, so only genuinely unpersisted output is recovered.
            streamed_content_parts: list[str] = []
            streamed_thinking_parts: list[str] = []
            try:
                # Observe a stop that was requested before this iteration
                # began, including one set before turn_scope was entered.
                # No provider request or before-model setup should start.
                check_stop()

                # ── before_model hooks ───────────────────────────────────
                for hook in hooks:
                    fn = getattr(hook, "before_model", None)
                    if fn:
                        await fn(history, iteration, agent.name)

                # Stream deltas to frontend as tokens arrive
                response: ChatResponse | None = None
                streamed_deltas = False
                async for chunk in _stream_chat_with_retries(
                    provider,
                    model=agent.model,
                    messages=history.messages,
                    tools=agent_state.tools,
                    options=agent.options,
                    think=agent.think,
                ):
                    if isinstance(chunk, ChatDelta):
                        streamed_deltas = True
                        if chunk.content:
                            streamed_content_parts.append(chunk.content)
                        if chunk.thinking:
                            streamed_thinking_parts.append(chunk.thinking)
                        try:
                            publish_event(
                                AgentEvent(
                                    payload=ContentPayload(
                                        type="content",
                                        content=chunk.content,
                                        thinking=chunk.thinking,
                                        delta=True,
                                    )
                                )
                            )
                        except Exception:  # pragma: no cover - defensive
                            logger.exception("Failed to publish delta event")
                        # Check for a stop after each token so a stop is
                        # noticed mid-stream; the unwind handler below
                        # persists whatever already streamed.
                        check_stop()
                    elif isinstance(chunk, ChatResponse):
                        response = chunk

                if response is None:
                    raise ToolLoopError("No ChatResponse received from provider")

                # ── after_model hooks (chain: each can rewrite response) ─
                for hook in hooks:
                    fn = getattr(hook, "after_model", None)
                    if fn:
                        response = await fn(response, history, iteration, agent.name)

                content = response.message.content
                thinking = response.message.thinking
                tool_calls = response.message.tool_calls
                # Some providers (e.g. Ollama) don't issue tool_call ids.
                # Mint one synchronously so iteration events, tool_result
                # events, and the persisted assistant message all share a
                # stable identifier — otherwise parallel tool calls race
                # in publish order and the pairing back to the originating
                # call becomes positional and fragile.
                for tc in tool_calls or []:
                    if not tc.id:
                        tc.id = f"call_{uuid.uuid4().hex[:8]}"
                # Emit full content only if no deltas were streamed (fallback path)
                if not streamed_deltas:
                    try:
                        publish_event(
                            AgentEvent(
                                payload=ContentPayload(
                                    type="content",
                                    content=content,
                                    thinking=thinking,
                                )
                            )
                        )
                    except Exception:  # pragma: no cover - defensive
                        logger.exception("Failed to publish model AgentEvent event")
                _publish_iteration(
                    iteration - 1,
                    content=content,
                    thinking=thinking,
                    tool_calls=[
                        IterationToolCall(
                            id=tc.id,
                            name=tc.function.name,
                            arguments=tc.function.arguments,
                        )
                        for tc in (tool_calls or [])
                    ],
                )
                # The iteration is fully persisted; clear the accumulators so
                # a later interruption (e.g. during tool execution) doesn't
                # re-persist this output as a partial.
                streamed_content_parts = []
                streamed_thinking_parts = []
                if content is not None:
                    final_content = content

                if not tool_calls:
                    return final_content

                tool_names = [tc.function.name for tc in tool_calls]
                logger.debug("Executing %d tool call(s) for '%s': %s", len(tool_calls), agent.name, tool_names)

                parallel = parallel_cfg.enabled and len(tool_calls) > 1
                if parallel:
                    logger.info(
                        "Running %d tool calls in parallel for '%s' (max_concurrent=%d)",
                        len(tool_calls),
                        agent.name,
                        parallel_cfg.max_concurrent,
                    )
                sem = asyncio.Semaphore(parallel_cfg.max_concurrent if parallel else 1)

                async def _run(
                    tc_item: ToolCall,
                    semaphore: asyncio.Semaphore,
                ) -> None:
                    async with semaphore:
                        await _run_tool_with_hooks(tc_item, agent_state.tools, hooks)

                await asyncio.gather(*[_run(tc, sem) for tc in tool_calls])

            except StopRequestedError:
                logger.info("Agent '%s' tool loop stopped by user request", agent.name)
                partial = _persist_partial(
                    streamed_content_parts,
                    streamed_thinking_parts,
                    iteration,
                )
                if partial is not None:
                    # StopRequestedError re-raises below, so no caller
                    # receives this as a return value. This only preserves
                    # the on_turn_end hook contract for hooks that inspect
                    # content.
                    final_content = partial
                raise
            except Exception as exc:
                logger.exception("Unhandled exception in tool loop")
                # Keep whatever streamed before the failure — the user
                # already saw it, and the error event follows it.
                _persist_partial(
                    streamed_content_parts,
                    streamed_thinking_parts,
                    iteration,
                )
                error_msg = (
                    str(exc) if isinstance(exc, ProviderError) else "An error occurred while processing your message."
                )
                retryable = isinstance(exc, ProviderError) and exc.retryable
                publish_event(
                    AgentEvent(
                        payload=ErrorPayload(
                            type="error",
                            message=error_msg,
                            retryable=retryable,
                        )
                    )
                )
                raise ToolLoopError(error_msg) from exc
    finally:
        for hook in hooks:
            fn = getattr(hook, "on_turn_end", None)
            if fn:
                try:
                    fn(final_content, agent.name)
                except Exception:  # pragma: no cover - defensive
                    logger.exception("on_turn_end hook failed")
