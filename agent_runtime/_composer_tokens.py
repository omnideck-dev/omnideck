"""Composer shortcut tokens: resolve chat shortcuts like `/skill` into run effects.

The chat composer lets a user insert a shortcut token — a trigger character
followed by a name, such as `/review-code` — normally by picking one from the
composer's own autocomplete. Each trigger character has a handler that
resolves the name against live server state into an effect, which the runner
applies before the agent runs: `/` loads a skill. The message itself reaches
the model exactly as typed.

A token whose name doesn't resolve — a typo, a stale name, or incidental
text that merely looks like one (a path such as `/etc/hosts`, a URL segment)
— is not a command and has no effect.
"""

import logging
import re
from dataclasses import dataclass
from functools import cached_property
from typing import Literal, Protocol

from agent_core.agent_capabilities import AgentCapabilities
from agent_core.events import AgentEvent, SkillLoadedPayload, publish_event
from agent_core.skills import skill_slug
from agents import AgentProfile
from skills._store import SkillRecord, list_public_skill_records

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LoadSkill:
    """Attach a skill to the agent before it runs."""

    record: SkillRecord


# One variant per kind of shortcut effect.
ComposerEffect = LoadSkill


class _TokenHandler(Protocol):
    trigger: str

    def resolve(self, ref: str) -> ComposerEffect | None:
        """Return the effect ``ref`` names, or None when it names nothing."""
        ...


def _match_skill(ref: str, skills: list[SkillRecord]) -> SkillRecord | None:
    """Exact id, then exact name, then a case-insensitive name, id, or slug
    match that fits exactly one skill.

    Names are unique only with exact case, and one skill's slug can equal
    another's id, so looser matches resolve only when unambiguous. The
    composer applies the same order when it picks a token to insert.
    """
    for skill in skills:
        if skill.id == ref:
            return skill
    for skill in skills:
        if skill.name == ref:
            return skill
    lowered = ref.lower()
    matches = {
        skill.id: skill
        for skill in skills
        if lowered in (skill.name.lower(), skill.id.lower(), skill_slug(skill.name))
    }
    return next(iter(matches.values())) if len(matches) == 1 else None


class _SkillTokens:
    """`/skill-name`: load a skill into the current run."""

    trigger = "/"

    @cached_property
    def _skills(self) -> list[SkillRecord]:
        return list_public_skill_records()

    def resolve(self, ref: str) -> ComposerEffect | None:
        record = _match_skill(ref, self._skills)
        return LoadSkill(record) if record is not None else None


def _handlers_for(profile: AgentProfile) -> list[_TokenHandler]:
    """The shortcut handlers available to an agent with ``profile``.

    A handler is left out when the agent can't do what its effect needs, so
    the token stays plain text.
    """
    handlers: list[_TokenHandler] = []
    if profile.allow_load_skills:
        handlers.append(_SkillTokens())
    return handlers


def resolve_composer_effects(text: str, profile: AgentProfile) -> list[ComposerEffect]:
    """Find the effects of the shortcut tokens in a typed message.

    A token is a handler's trigger character followed by a name, at the
    start of the message or after whitespace. Tokens that resolve yield
    their effects in message order, each distinct effect once; the rest
    are plain text.
    """
    handlers = {handler.trigger: handler for handler in _handlers_for(profile)}
    if not handlers:
        return []

    triggers = "".join(re.escape(trigger) for trigger in handlers)
    token_re = re.compile(rf"(?:^|(?<=\s))(?P<trigger>[{triggers}])(?P<ref>\S+)")

    effects: list[ComposerEffect] = []
    for match in token_re.finditer(text):
        effect = handlers[match["trigger"]].resolve(match["ref"])
        if effect is not None and effect not in effects:
            effects.append(effect)
    return effects


async def apply_composer_effects(effects: list[ComposerEffect], capabilities: AgentCapabilities) -> None:
    """Apply shortcut effects to the agent about to run, publishing each outcome."""
    for effect in effects:
        await _load_skill(effect, capabilities)


async def _load_skill(effect: LoadSkill, capabilities: AgentCapabilities) -> None:
    record = effect.record
    status: Literal["loaded", "already_loaded", "unavailable"]
    if record.id in capabilities.skill_ids:
        status = "already_loaded"
    else:
        # The capabilities' own resolver binds the same tool catalog that
        # the model's load_skill tool uses.
        resolver = capabilities.skill_resolver
        skill = await resolver(record.name) if resolver is not None else None
        if skill is None:
            logger.warning("composer skill %r could not be resolved at run time", record.id)
            status = "unavailable"
        else:
            capabilities.load(skill)
            status = "loaded"
    publish_event(AgentEvent(payload=SkillLoadedPayload(
        type="skill_loaded", skill_id=record.id, skill_name=record.name, status=status,
    )))
