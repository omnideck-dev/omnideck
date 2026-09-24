"""Expose child execution as a tool bound to its owning parent."""

from collections.abc import Awaitable, Callable

ChildInvoker = Callable[[str, str, str], Awaitable[str]]


def make_spawn_tool(invoke: ChildInvoker) -> Callable[..., Awaitable[str]]:
    """Create a model-facing tool without exposing runtime identity as arguments."""

    async def spawn_agent(
        instructions: str,
        profile: str,
        agent_name: str = "SUB_AGENT",
    ) -> str:
        """Spawn a sub-agent to handle a task in isolation.

        The sub-agent runs in its own context window. Use this for tasks that
        are long-running or produce large intermediate output (long browsing
        sessions, multi-file code generation) so they don't consume the
        parent's context.

        Call list_agent_profiles() to see available profiles.

        Args:
            instructions: Complete, self-contained task description. Include
                EVERYTHING the agent needs — it has zero context from the parent.
            profile: Agent profile ID (e.g. "code_expert", "research_agent").
                Determines the model, skills, system prompt, and inference
                parameters.
            agent_name: Short UPPERCASE name for the UI (e.g. DATA_ANALYST).

        Returns:
            Summary of what the sub-agent accomplished.
        """
        return await invoke(instructions, profile, agent_name)

    return spawn_agent
