"""Structural contracts for optional execution-hook phases.

A hook implements one or more phases; it need not inherit a base class or supply
no-op methods for the others. Model phases are async; tool/lifecycle phases are
synchronous, matching the executor's dispatch contract.
"""

from typing import Any, Protocol, TypeAlias

from sdk.context import ConversationHistory
from sdk.providers import ChatResponse


class TurnStartHook(Protocol):
    def on_turn_start(self, agent_name: str) -> None: ...


class BeforeModelHook(Protocol):
    async def before_model(self, history: ConversationHistory, iteration: int, agent_name: str) -> None: ...


class AfterModelHook(Protocol):
    async def after_model(
        self,
        response: ChatResponse,
        history: ConversationHistory,
        iteration: int,
        agent_name: str,
    ) -> ChatResponse: ...


class BeforeToolHook(Protocol):
    def before_tool(self, tool_name: str, tool_arguments: dict[str, Any]) -> str | None: ...


class AfterToolHook(Protocol):
    def after_tool(self, tool_name: str, tool_arguments: dict[str, Any], tool_result: str) -> str: ...


class TurnEndHook(Protocol):
    def on_turn_end(self, final_content: str | None, agent_name: str) -> None: ...


Hook: TypeAlias = TurnStartHook | BeforeModelHook | AfterModelHook | BeforeToolHook | AfterToolHook | TurnEndHook
