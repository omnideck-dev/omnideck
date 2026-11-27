"""Tool loop utilities for executing chat-based LLM interactions with tool calls."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from agent_core.hooks._types import Hook
from agent_core.agent import Agent
from agent_core.context import ConversationHistory
from agent_core.events import (
    AgentEvent,
    ContentPayload,
    ErrorPayload,
    IterationPayload,
    IterationToolCall,
    ToolResultPayload,
    publish_event,
)
from agent_core.providers import ChatDelta, ChatResponse, ProviderError, ToolCall, Provider, TokenUsage
from agent_core.agent_capabilities import AgentCapabilities
from agent_core.tools import _execute_tool_call

from agent_core.control import StopRequestedError, get_execution_control
from ._turn import check_stop
from ._models import ExecutionContext, ExecutionResult, ToolLoopError

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
    provider: Provider,
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


@dataclass(frozen=True)
class _HookPhases:
    turn_start: list[Callable[[str], None]]
    before_model: list[Callable[[ConversationHistory, int, str], Awaitable[None]]]
    after_model: list[Callable[[ChatResponse, ConversationHistory, int, str], Awaitable[ChatResponse]]]
    before_tool: list[Callable[[str, dict[str, Any]], str | None]]
    after_tool: list[Callable[[str, dict[str, Any], str], str]]
    turn_end: list[Callable[[str | None, str], None]]

    @classmethod
    def from_hooks(cls, hooks: Sequence[Hook]) -> _HookPhases:
        def collect(name: str) -> list[Any]:
            return [fn for hook in hooks if (fn := getattr(hook, name, None))]

        return cls(
            turn_start=collect("on_turn_start"),
            before_model=collect("before_model"),
            after_model=collect("after_model"),
            before_tool=collect("before_tool"),
            after_tool=collect("after_tool"),
            turn_end=collect("on_turn_end"),
        )


async def _run_tool_with_hooks(
    tool_call: ToolCall,
    tools: list[Callable[..., Any]],
    phases: _HookPhases,
) -> None:
    """Execute a single tool call with before/after hooks.

    Publishes a ``ToolResultPayload`` for the call. The result also flows
    into the history view through that event — there is no return value.
    """
    tool_name = tool_call.function.name
    tool_arguments = tool_call.function.arguments

    intercepted = None
    for before_tool in phases.before_tool:
        intercepted = before_tool(tool_name, tool_arguments)
        if intercepted is not None:
            break

    if intercepted is not None:
        tool_result = intercepted
    else:
        tool_result = await _execute_tool_call(tool_name, tool_arguments, tools)

    for after_tool in phases.after_tool:
        tool_result = after_tool(tool_name, tool_arguments, tool_result)

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


class AgentExecutor:
    """Execute an agent with explicit dependencies and execution-local state."""

    async def execute(
        self,
        *,
        history: ConversationHistory,
        agent: Agent,
        capabilities: AgentCapabilities,
        provider: Provider,
        context: ExecutionContext,
        hooks: Sequence[Hook] | None = None,
        max_parallel_tools: int = 1,
    ) -> ExecutionResult:
        if max_parallel_tools < 1:
            raise ValueError("max_parallel_tools must be positive")
        with context.bind(agent.name, capabilities):
            try:
                return await _AgentRun(
                    history=history,
                    agent=agent,
                    capabilities=capabilities,
                    provider=provider,
                    phases=_HookPhases.from_hooks(hooks or []),
                    max_parallel_tools=max_parallel_tools,
                ).run()
            finally:
                context.control.accepting_nudges = False


class _AgentRun:
    def __init__(
        self,
        *,
        history: ConversationHistory,
        agent: Agent,
        capabilities: AgentCapabilities,
        provider: Provider,
        phases: _HookPhases,
        max_parallel_tools: int,
    ) -> None:
        self._history = history
        self._agent = agent
        self._capabilities = capabilities
        self._provider = provider
        self._phases = phases
        self._max_parallel_tools = max_parallel_tools
        self._usage = TokenUsage()
        # Tracks the latest assistant content for the successful execution return
        # value and the on_turn_end hook payload. Persistence reads history, not
        # this variable.
        self._final_content: str | None = None
        self._iteration = 0
        # Accumulates this iteration's streamed output so it can be persisted
        # if the turn is interrupted. Reset per iteration and cleared once the
        # full iteration event publishes, so only genuinely unpersisted output
        # is recovered.
        self._streamed_content_parts: list[str] = []
        self._streamed_thinking_parts: list[str] = []

    async def run(self) -> ExecutionResult:
        for on_turn_start in self._phases.turn_start:
            on_turn_start(self._agent.name)
        try:
            while True:
                self._iteration += 1
                logger.debug("Tool loop iteration %d for agent '%s'", self._iteration, self._agent.name)
                self._streamed_content_parts = []
                self._streamed_thinking_parts = []
                try:
                    result = await self._step()
                except StopRequestedError:
                    return self._stopped()
                except Exception as exc:
                    return self._failed(exc)
                if result is not None:
                    return result
        finally:
            self._end_turn()

    async def _step(self) -> ExecutionResult | None:
        # Observe a stop that was requested before this iteration
        # began. No provider request or before-model setup should start.
        check_stop()
        for before_model in self._phases.before_model:
            await before_model(self._history, self._iteration, self._agent.name)

        response, streamed_deltas = await self._call_model()
        for after_model in self._phases.after_model:
            response = await after_model(response, self._history, self._iteration, self._agent.name)

        tool_calls = self._publish_step(response, streamed_deltas)
        if not tool_calls:
            control = get_execution_control()
            if control is not None and control.nudges:
                return None
            return ExecutionResult("success", self._final_content, response.done_reason, self._usage)

        await self._run_tools(tool_calls)
        return None

    async def _call_model(self) -> tuple[ChatResponse, bool]:
        response: ChatResponse | None = None
        streamed_deltas = False
        async for chunk in _stream_chat_with_retries(
            self._provider,
            model=self._agent.model,
            messages=self._history.messages,
            tools=self._capabilities.tools,
            options=self._agent.options,
            think=self._agent.think,
        ):
            if isinstance(chunk, ChatDelta):
                streamed_deltas = True
                if chunk.content:
                    self._streamed_content_parts.append(chunk.content)
                if chunk.thinking:
                    self._streamed_thinking_parts.append(chunk.thinking)
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
                # Check for a stop after each token so a stop is
                # noticed mid-stream.
                check_stop()
            elif isinstance(chunk, ChatResponse):
                response = chunk

        if response is None:
            raise ToolLoopError("No ChatResponse received from provider")

        self._usage += response.usage
        return response, streamed_deltas

    def _publish_step(self, response: ChatResponse, streamed_deltas: bool) -> list[ToolCall]:
        content = response.message.content
        thinking = response.message.thinking
        tool_calls = response.message.tool_calls or []
        # Some providers (e.g. Ollama) don't issue tool_call ids.
        # Mint one synchronously so iteration events, tool_result
        # events, and the persisted assistant message all share a
        # stable identifier — otherwise parallel tool calls race
        # in publish order and the pairing back to the originating
        # call becomes positional and fragile.
        for tc in tool_calls:
            if not tc.id:
                tc.id = f"call_{uuid.uuid4().hex[:8]}"
        if not streamed_deltas:
            publish_event(
                AgentEvent(
                    payload=ContentPayload(
                        type="content",
                        content=content,
                        thinking=thinking,
                    )
                )
            )
        _publish_iteration(
            self._iteration - 1,
            content=content,
            thinking=thinking,
            tool_calls=[
                IterationToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                )
                for tc in tool_calls
            ],
        )
        self._streamed_content_parts = []
        self._streamed_thinking_parts = []
        if content is not None:
            self._final_content = content
        return tool_calls

    async def _run_tools(self, tool_calls: list[ToolCall]) -> None:
        tool_names = [tc.function.name for tc in tool_calls]
        logger.debug("Executing %d tool call(s) for '%s': %s", len(tool_calls), self._agent.name, tool_names)

        parallel = self._max_parallel_tools > 1 and len(tool_calls) > 1
        if parallel:
            logger.info(
                "Running %d tool calls in parallel for '%s' (max_concurrent=%d)",
                len(tool_calls),
                self._agent.name,
                self._max_parallel_tools,
            )
        semaphore = asyncio.Semaphore(self._max_parallel_tools if parallel else 1)

        async def run_one(tool_call: ToolCall) -> None:
            async with semaphore:
                await _run_tool_with_hooks(tool_call, self._capabilities.tools, self._phases)

        # A stopped child can raise while its siblings are still
        # unwinding. Keep the parent scope (and its event observers)
        # alive until the whole batch has finished, including on
        # cancellation, then propagate the control/error outcome.
        results = await asyncio.gather(*[run_one(tc) for tc in tool_calls], return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result

    def _keep_partial_output(self) -> None:
        partial = _persist_partial(
            self._streamed_content_parts,
            self._streamed_thinking_parts,
            self._iteration,
        )
        if partial is not None:
            self._final_content = partial

    def _stopped(self) -> ExecutionResult:
        logger.info("Agent '%s' tool loop stopped by user request", self._agent.name)
        self._keep_partial_output()
        return ExecutionResult("stopped", self._final_content, "stopped", self._usage)

    def _failed(self, exc: Exception) -> ExecutionResult:
        logger.exception("Unhandled exception in tool loop")
        # Keep whatever streamed before the failure — the user
        # already saw it, and the error event follows it.
        self._keep_partial_output()
        error_msg = (
            str(exc)
            if isinstance(exc, ProviderError)
            else "An error occurred while processing your message."
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
        return ExecutionResult("error", self._final_content, "error", self._usage, error_msg, retryable)

    def _end_turn(self) -> None:
        for on_turn_end in self._phases.turn_end:
            try:
                on_turn_end(self._final_content, self._agent.name)
            except Exception:  # pragma: no cover - defensive
                logger.exception("on_turn_end hook failed")
