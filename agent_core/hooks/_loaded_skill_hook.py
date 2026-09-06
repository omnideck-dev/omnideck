"""Hook that injects loaded skill prompts into the system message."""

from __future__ import annotations

import logging

from agent_core.context import ConversationHistory
from agent_core.agent_capabilities import get_active_agent_capabilities

logger = logging.getLogger(__name__)

# Marker used to find and replace the capability/skill section in the system message.
_PROMPT_EXTENSIONS_MARKER = "\n── Capabilities & Skills ──"


class LoadedSkillHook:
    """Injects loaded skill prompts into the system message before each model call.

    Reads from the active AgentCapabilities to build a skill prompt section and
    appends it to the system message. On each iteration the section is
    rebuilt so newly loaded skills appear immediately. Existing content
    (base instruction, memory) is preserved.
    """

    async def before_model(
        self,
        history: ConversationHistory,
        iteration: int,
        agent_name: str,
    ) -> None:
        """Rebuild the skill section of the system message."""
        agent_capabilities = get_active_agent_capabilities()
        if agent_capabilities is None:
            return

        skill_section = agent_capabilities.build_prompt_extensions()

        messages = history.messages
        if not messages or messages[0].get("role") != "system":
            return

        current = messages[0]["content"] or ""

        # Strip any existing skill section before appending the current one.
        marker_pos = current.find(_PROMPT_EXTENSIONS_MARKER)
        if marker_pos >= 0:
            base = current[:marker_pos]
        else:
            base = current

        history.set_system_message(base + skill_section)
