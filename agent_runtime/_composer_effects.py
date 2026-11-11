"""Composer effects: what a user's explicit composer selections do to a run.

When a user picks a shortcut in the chat composer — a skill via `/` — the
composer sends that selection by id alongside the message. Each selection
becomes an effect the runner applies before the agent runs: a selected skill
is loaded, so its instructions and tools are present from the first model
call. The message itself reaches the model exactly as typed.

Selections only ever come from the composer. Text that merely looks like a
shortcut — in a message, a routine task, or a spawned agent's instructions
— is never interpreted.
"""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from agent_core.agent_capabilities import AgentCapabilities
from agent_core.events import AgentEvent, SkillLoadedPayload, publish_event
from skills._policy import is_reserved_skill_id
from skills._store import get_skill_record

from ._models import SelectedSkill

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LoadSkill:
    """Attach a selected skill to the agent before it runs."""

    selection: SelectedSkill


# One variant per kind of composer effect.
ComposerEffect = LoadSkill


def composer_effects(skills: Sequence[SelectedSkill]) -> list[ComposerEffect]:
    """The effects of a run's composer selections, in order, each skill once."""
    effects: list[ComposerEffect] = []
    seen: set[str] = set()
    for skill in skills:
        if skill.id not in seen:
            seen.add(skill.id)
            effects.append(LoadSkill(skill))
    return effects


async def apply_composer_effects(effects: Sequence[ComposerEffect], capabilities: AgentCapabilities) -> None:
    """Apply composer effects to the agent about to run, publishing each outcome."""
    for effect in effects:
        await _load_skill(effect, capabilities)


async def _load_skill(effect: LoadSkill, capabilities: AgentCapabilities) -> None:
    selection = effect.selection
    # The label recorded for history: the skill's name when it was loaded,
    # or the name the user saw if it can no longer be found.
    name = selection.name
    status: Literal["loaded", "already_loaded", "unavailable"]
    record = None if is_reserved_skill_id(selection.id) else await asyncio.to_thread(get_skill_record, selection.id)
    if record is None:
        logger.warning("selected skill %r no longer exists", selection.id)
        status = "unavailable"
    elif record.id in capabilities.skill_ids:
        name = record.name
        status = "already_loaded"
    else:
        name = record.name
        # The capabilities' own resolver binds the same tool catalog that
        # the model's load_skill tool uses. Loading here doesn't depend on
        # that tool being granted: an explicit user selection is not the
        # model loading skills on its own.
        resolver = capabilities.skill_resolver
        skill = await resolver(record.name) if resolver is not None else None
        if skill is None:
            logger.warning("selected skill %r could not be resolved", selection.id)
            status = "unavailable"
        else:
            capabilities.load(skill)
            status = "loaded"
    publish_event(AgentEvent(payload=SkillLoadedPayload(
        type="skill_loaded", skill_id=selection.id, skill_name=name, status=status,
    )))
