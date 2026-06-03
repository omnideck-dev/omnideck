"""Core tools included in every agent's tool set."""

from collections.abc import Callable
from typing import Any

from sdk.tools._integration_tools import all_integration_tools


async def get_core_tools() -> list[Callable[..., Any]]:
    """Return tools that every agent gets regardless of skill configuration.

    Async because the integration tool gating awaits the integrations cache,
    which loads lazily on first use after app startup.

    Lazy imports to avoid circular dependencies.
    """
    from sdk.skills._tools import list_available_skills, load_skill
    from agents._list_profiles_tool import list_agent_profiles
    from sdk.tools._spawn_agent import spawn_agent
    from tools.scratchpad import recall_from_scratchpad, save_to_scratchpad
    from tools.virtual_computer.describe_image import describe_image
    from tools.virtual_computer.file_output import send_file
    from tools.virtual_computer.play_audio import play_audio

    tools = [
        save_to_scratchpad,
        recall_from_scratchpad,
        load_skill,
        list_available_skills,
        list_agent_profiles,
        spawn_agent,
        send_file,
        play_audio,
        describe_image,
    ]

    tools.extend(await all_integration_tools())

    return tools
