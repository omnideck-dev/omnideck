"""The load_skill and list_available_skills meta-tools."""

import logging

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from ._policy import is_reserved_skill_id
from ._resolve import resolve_skill_by_name
from ._store import list_skill_records
from sdk.agent_capabilities import get_active_agent_capabilities

logger = logging.getLogger(__name__)

_console = Console(stderr=True)


def _log_skill_loaded(skill_name: str, description: str, new_tools: list[str]) -> None:
    """Print a Rich panel when a skill is loaded."""
    body = Text()
    body.append("skill: ", style="bold")
    body.append(skill_name, style="bright_magenta")
    body.append(f"  ({description})", style="dim")
    if new_tools:
        body.append(f"\ntools: ", style="bold")
        body.append(", ".join(new_tools), style="bright_magenta")
    else:
        body.append("\ntools: ", style="bold")
        body.append("(none — guidance only)", style="dim")

    _console.print(
        Panel(
            body,
            title="[bold bright_magenta]⚡ Skill Loaded[/bold bright_magenta]",
            border_style="bright_magenta",
            expand=False,
        )
    )


def _log_skill_already_loaded(skill_name: str) -> None:
    """Print a dim panel when a skill is requested but already loaded."""
    body = Text()
    body.append(skill_name, style="bright_magenta")
    body.append("  (already loaded)", style="dim")

    _console.print(
        Panel(
            body,
            title="[bold dim]⚡ Skill[/bold dim]",
            border_style="dim",
            expand=False,
        )
    )


def _log_skill_error(skill_name: str, error: str) -> None:
    """Print a red panel when a skill load fails."""
    body = Text()
    body.append("skill: ", style="bold")
    body.append(skill_name, style="red")
    body.append(f"\nerror: ", style="bold")
    body.append(error, style="red")

    _console.print(
        Panel(
            body,
            title="[bold red]⚡ Skill Error[/bold red]",
            border_style="red",
            expand=False,
        )
    )


def _available_skill_names() -> list[str]:
    return [r.name for r in list_skill_records() if not is_reserved_skill_id(r.id)]


def list_available_skills() -> str:
    """List all skills that can be loaded with load_skill.

    A skill whose categories grant no tools right now (e.g. its capability isn't
    connected, or a feature is off) still appears — it simply loads no tools until then.

    Returns:
        A formatted list of skill names and descriptions.
    """
    records = [r for r in list_skill_records() if not is_reserved_skill_id(r.id)]
    if not records:
        return "No skills available."
    lines = [f"  - {r.name}: {r.description}" for r in records]
    return "Available skills:\n" + "\n".join(lines)


async def load_skill(name: str) -> str:
    """Load a skill to gain its tools and capabilities.

    Call list_available_skills() first to see what is available.
    Already-loaded skills return instantly without duplication.

    Args:
        name: Skill name from the catalog.

    Returns:
        Confirmation message, or an error message.
    """
    agent_capabilities = get_active_agent_capabilities()
    if agent_capabilities is None:
        return "Error: no active skill scope (internal error)"

    record = next(
        (item for item in list_skill_records() if item.name == name and not is_reserved_skill_id(item.id)),
        None,
    )
    skill = await resolve_skill_by_name(name) if record is not None else None
    if skill is None:
        available = ", ".join(_available_skill_names())
        error_msg = f"Unknown skill '{name}'. Available: {available}"
        _log_skill_error(name, error_msg)
        return error_msg

    if skill.id in agent_capabilities.skill_ids:
        _log_skill_already_loaded(name)
        return f"Skill '{name}' is already loaded."

    agent_capabilities.load(skill)
    skill_tools = [getattr(t, "__name__", "?") for t in skill.tools]
    _log_skill_loaded(name, skill.description, skill_tools)
    return f"Loaded skill '{name}' ({len(skill_tools)} tools). Instructions added to system prompt."
