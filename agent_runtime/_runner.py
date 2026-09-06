"""Prepare and execute root and child agents inside an application RunSession."""

from __future__ import annotations

import asyncio
import logging
from functools import partial
from collections.abc import Sequence
from uuid import uuid4

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from agents import AgentProfile, get_agent_profile
from browser.runtime import get_browser_runtime
from config import load_config
from conversations import save_conversation_profile
from agent_core import AgentExecutor, default_hooks
from agent_core.context import ContextManager, ConversationHistory
from agent_core.control import StopRequestedError
from agent_core.events import (
    AgentEvent,
    ErrorPayload,
    SpawnRequestedPayload,
    UserAttachment,
    UserMessagePayload,
    agent_span,
    publish_event,
)
from agent_core.turn import ExecutionContext, ExecutionResult, ToolLoopError
from tools.virtual_computer.receive_file import receive_attachment

from ._compaction import LLMCompactionStrategy
from ._factory import AgentFactory, persist_loaded_skills
from ._models import AgentRunRequest, RunAttachment, RunPolicy
from ._scratchpad_hook import ScratchpadHook
from ._session import RunSession
from ._spawn import make_spawn_tool

logger = logging.getLogger(__name__)
_console = Console(stderr=True)
_CHILD_POLICY = RunPolicy(restore_skills=False, persist_skills=False, include_memory=False)


class AgentRunner:
    """Execute one agent; the supplied session owns the surrounding run."""

    def __init__(self, *, factory: AgentFactory | None = None) -> None:
        self._factory = factory if factory is not None else AgentFactory()

    async def run(self, request: AgentRunRequest, session: RunSession) -> ExecutionResult:
        """Translate accepted root input into the shared execution path."""
        try:
            session.root_context.control.check_stop()
            profile = self._factory.resolve_profile(request.profile_id)
            _log_turn_start(profile)
            instruction = request.message
            attachments: list[UserAttachment] = []
            if request.attachments:
                instruction, attachments = _augment_message_with_attachments(request.message, request.attachments)
            save_conversation_profile(request.conversation_id, profile.id)
            return await self.execute(
                session=session,
                context=session.root_context,
                profile=profile,
                message=request.message,
                instruction=instruction,
                attachments=attachments,
                name=request.policy.agent_name,
                policy=request.policy,
            )
        except StopRequestedError:
            return ExecutionResult("stopped")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Failed to prepare root agent for '%s'", request.conversation_id)
            session.add_event(
                AgentEvent(
                    payload=ErrorPayload(
                        type="error",
                        message="An error occurred while processing your message.",
                    )
                )
            )
            return ExecutionResult("error", error=str(exc))

    async def execute(
        self,
        *,
        session: RunSession,
        context: ExecutionContext,
        profile: AgentProfile,
        message: str,
        name: str | None = None,
        instruction: str | None = None,
        attachments: list[UserAttachment] | None = None,
        policy: RunPolicy = _CHILD_POLICY,
        correlation_id: str | None = None,
    ) -> ExecutionResult:
        """Use explicit session-owned identity, controls, history, and event delivery."""
        prepared = None
        child_history = None
        cancelled = False
        result = ExecutionResult("error", error="Execution did not complete")
        try:
            context.control.check_stop()
            spawn_agent = make_spawn_tool(partial(self._invoke_child, session, context))
            prepared = await self._factory.prepare(
                profile,
                spawn_agent=spawn_agent,
                name=name,
                restore_from_conversation=session.conversation_id if policy.restore_skills else None,
                include_memory=policy.include_memory,
            )
            agent = prepared.agent
            history = session.history
            if context.parent_execution_id is not None:
                child_history = ConversationHistory(
                    conversation_id=session.conversation_id, agent_id=context.execution_id
                )
                history = child_history
                session.subscribe(history.handle_event)
            if history is None:
                raise RuntimeError("RunSession has no prepared history")
            history.set_system_message(prepared.system_prompt)
            ctx_manager = ContextManager(
                history=history,
                agent_capabilities=prepared.capabilities,
                context_limit=agent.context_window,
                agent_name=agent.name,
                compaction_threshold=agent.compaction_threshold,
                strategies=[LLMCompactionStrategy(threshold=agent.compaction_threshold)],
            )
            hooks = default_hooks(agent, max_iterations=agent.max_iterations, ctx_manager=ctx_manager)
            hooks.append(ScratchpadHook())
            if correlation_id is not None:
                publish_event(
                    AgentEvent(payload=SpawnRequestedPayload(type="spawn_requested", correlation_id=correlation_id))
                )
            async with agent_span(
                agent.name,
                instruction=instruction if instruction is not None else message,
                agent_capabilities=prepared.capabilities,
                profile_name=profile.name,
                correlation_id=correlation_id,
                execution=context,
            ):
                await get_browser_runtime().prepare_current_agent_browser(
                    agent_profile_id=profile.id,
                    browser_profile_id=profile.browser_profile_id,
                )
                publish_event(
                    AgentEvent(
                        payload=UserMessagePayload(type="user_message", content=message, attachments=attachments or [])
                    )
                )
                parallel = load_config().parallel
                result = await AgentExecutor().execute(
                    history=history,
                    agent=agent,
                    capabilities=prepared.capabilities,
                    provider=prepared.provider,
                    context=context,
                    max_parallel_tools=parallel.max_concurrent if parallel.enabled else 1,
                    hooks=hooks,
                )
                result.raise_for_status()
        except asyncio.CancelledError:
            cancelled = True
            result = ExecutionResult("stopped")
            raise
        except StopRequestedError:
            if result.status != "stopped":
                result = ExecutionResult("stopped")
        except ToolLoopError as exc:
            if result.status != "error" or result.error == "Execution did not complete":
                result = ExecutionResult("error", error=str(exc))
        except Exception as exc:
            result = ExecutionResult("error", error=str(exc))
            raise
        finally:
            session.finish_execution(context, result)
            if child_history is not None:
                session.unsubscribe(child_history.handle_event)
            if (
                policy.persist_skills
                and not cancelled
                and prepared is not None
                and prepared.capabilities.loaded_skill_ids
            ):
                try:
                    persist_loaded_skills(prepared.capabilities, session.conversation_id)
                except Exception:
                    logger.exception("Failed to save loaded skills for '%s'", session.conversation_id)
        return result

    async def _invoke_child(
        self,
        session: RunSession,
        parent: ExecutionContext,
        instructions: str,
        profile: str,
        agent_name: str,
    ) -> str:
        session.require_parent(parent)
        parent.control.check_stop()
        agent_profile = get_agent_profile(profile)
        if agent_profile is None:
            return f"Agent profile '{profile}' not found. Call list_agent_profiles() to see available profiles."
        if not agent_profile.enabled:
            return f"Agent profile '{profile}' is disabled and cannot be used by spawn_agent. Call list_agent_profiles() to see available profiles."
        child = session.create_child(parent)
        result = await self.execute(
            session=session,
            context=child,
            profile=agent_profile,
            message=instructions,
            name=agent_name,
            correlation_id=uuid4().hex,
        )
        result.raise_for_status()
        return (result.output or "").strip()


def _augment_message_with_attachments(
    message: str,
    run_attachments: Sequence[RunAttachment],
) -> tuple[str, list[UserAttachment]]:
    """Write attachments and return model text plus structured event metadata."""
    file_lines = []
    attachments: list[UserAttachment] = []
    for item in run_attachments:
        container_path = receive_attachment(
            base64_encoded=item.base64_encoded,
            content_type=item.content_type,
            filename=item.filename,
        )
        name = item.filename or "unnamed"
        file_lines.append(f"  - {name} ({item.content_type}) -> {container_path}")
        attachments.append(
            UserAttachment(
                filename=name,
                content_type=item.content_type,
                path=container_path,
            )
        )

    files_block = "\n".join(file_lines)
    augmented = f"{message}\n\n[Attached files written to virtual computer]\n{files_block}"
    return augmented, attachments


def _log_turn_start(profile: AgentProfile) -> None:
    """Print a Rich panel showing the active profile and its settings."""
    body = Text()
    body.append("profile: ", style="bold")
    body.append(profile.name, style="bright_magenta")
    body.append(f" ({profile.id})", style="dim")
    body.append("\nmodel:   ", style="bold")
    body.append(profile.model or "—", style="bright_yellow")
    if profile.skills:
        body.append("\nskills:  ", style="bold")
        body.append(", ".join(profile.skills), style="bright_cyan")
    params = []
    if profile.temperature is not None:
        params.append(f"temp={profile.temperature}")
    if profile.top_k is not None:
        params.append(f"top_k={profile.top_k}")
    if profile.top_p is not None:
        params.append(f"top_p={profile.top_p}")
    if profile.repeat_penalty is not None:
        params.append(f"repeat_penalty={profile.repeat_penalty}")
    if profile.num_predict is not None:
        params.append(f"num_predict={profile.num_predict}")
    if profile.context_window is not None:
        params.append(f"ctx={profile.context_window}")
    if profile.compaction_threshold is not None:
        params.append(f"compact@{int(profile.compaction_threshold * 100)}%")
    if profile.think:
        params.append("think")
    if profile.reasoning_effort is not None:
        params.append(f"reasoning_effort={profile.reasoning_effort}")
    if profile.reasoning_summary is not None:
        params.append(f"reasoning_summary={profile.reasoning_summary}")
    if profile.thinking_budget is not None:
        params.append(f"thinking_budget={profile.thinking_budget}")
    if profile.max_iterations is not None:
        params.append(f"max_iter={profile.max_iterations}")
    if params:
        body.append("\nparams:  ", style="bold")
        body.append(", ".join(params), style="dim")

    _console.print(
        Panel(
            body,
            title="[bold bright_magenta]🤖 Agent Turn[/bold bright_magenta]",
            border_style="bright_magenta",
            expand=False,
        )
    )


__all__ = ["AgentRunner"]
