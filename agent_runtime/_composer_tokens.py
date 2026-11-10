"""Composer shortcut tokens: resolve chat shortcuts like `/skill` into tool instructions.

The chat composer lets a user insert a shortcut token — a trigger character
followed by a name, such as `/review-code` — normally by picking one from the
composer's own autocomplete overlay. Each trigger character has a handler
that resolves the name against live server state. A resolved token, together
with the text that follows it, is rendered into an explicit natural-language
instruction naming the resolved id and the tool to call; the agent's own
tool-calling loop does the actual work.

A token whose name doesn't resolve — a typo, a stale name, or incidental
text that merely looks like one (a path such as `/etc/hosts`, a URL segment)
— is not a command. It is left as typed and read as part of the preceding
token's task text.

Resolution happens once, when the user's message is recorded. The result is
stored beside the typed text, so the transcript shows exactly what the user
typed and the model sees the same rendered instruction on every later turn.
"""

import re
from collections.abc import Callable
from functools import cached_property, partial
from typing import Protocol

from agents._agent_profiles import AgentProfile
from skills._policy import is_reserved_skill_id
from skills._store import SkillRecord, list_skill_records

# Renders a resolved token as an instruction, given the task text after it.
TokenRenderer = Callable[[str], str]


class _TokenHandler(Protocol):
    trigger: str

    def resolve(self, ref: str) -> TokenRenderer | None:
        """Return a renderer for ``ref``, or None when it names nothing."""
        ...


def _slugify(text: str) -> str:
    """Kebab-case a display name for token matching.

    Must stay behaviorally identical to the composer's client-side copy —
    the composer inserts these slugs, so any drift silently breaks
    resolution for multi-word names.
    """
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# A user who types the bare token with nothing after it hasn't given a task —
# they want the skill's own output (a joke, a draft, whatever it does),
# delivered directly. Without this, "load X and use it" reads like a system
# test spec (it even names a raw skill id), and models asked to "use" a
# freshly loaded capability with no further direction default to reporting on
# whether the mechanism worked instead of just doing the thing.
_NO_ARGS_DIRECTIVE = "use it — respond with what it produces, not a report on whether it loaded"


def _render_load(skill: SkillRecord, args: str) -> str:
    skill_desc = f'skill "{skill.name}" (id: {skill.id})'
    action = f'then use it to: {args}' if args else f'then {_NO_ARGS_DIRECTIVE}'
    return (
        f'Load {skill_desc} into your own current session using the load_skill tool, '
        f'{action}. Do not spawn a subagent for this — handle it yourself in this '
        f'conversation.'
    )


class _SkillTokens:
    """`/skill-name task`: load a skill into the current run and use it."""

    trigger = "/"

    @cached_property
    def _skills(self) -> list[SkillRecord]:
        # Reserved skills are app capabilities, not user-invocable skills.
        return [record for record in list_skill_records() if not is_reserved_skill_id(record.id)]

    def resolve(self, ref: str) -> TokenRenderer | None:
        lowered = ref.lower()
        for skill in self._skills:
            if skill.name.lower() == lowered or skill.id.lower() == lowered:
                return partial(_render_load, skill)
        # Two names that slugify identically are ambiguous; resolve neither.
        slug_matches = [skill for skill in self._skills if _slugify(skill.name) == lowered]
        if len(slug_matches) == 1:
            return partial(_render_load, slug_matches[0])
        return None


def _handlers_for(profile: AgentProfile) -> list[_TokenHandler]:
    """The shortcut handlers available to an agent with ``profile``.

    A handler is left out when the agent lacks the tool its instruction
    would name, so the token stays plain text rather than steering the
    model toward a tool it can't call.
    """
    handlers: list[_TokenHandler] = []
    if profile.allow_load_skills:
        handlers.append(_SkillTokens())
    return handlers


def resolve_composer_tokens(text: str, profile: AgentProfile) -> str | None:
    """Rewrite resolvable shortcut tokens in a typed message into tool instructions.

    A token is a handler's trigger character followed by a name, at the
    start of the message or after whitespace. Each resolved token is
    replaced, together with the task text up to the next resolved token,
    by its handler's instruction. Text before the first resolved token and
    unresolved tokens pass through as typed. Several resolved tokens get a
    leading instruction to perform them in order.

    Returns:
        The rewritten message, or None when no token resolved.
    """
    handlers = {handler.trigger: handler for handler in _handlers_for(profile)}
    if not handlers:
        return None

    triggers = "".join(re.escape(trigger) for trigger in handlers)
    token_re = re.compile(rf"(?:^|(?<=\s))(?P<trigger>[{triggers}])(?P<ref>\S+)")

    resolved: list[tuple[re.Match[str], TokenRenderer]] = []
    for match in token_re.finditer(text):
        renderer = handlers[match["trigger"]].resolve(match["ref"])
        if renderer is not None:
            resolved.append((match, renderer))
    if not resolved:
        return None

    pieces = [text[:resolved[0][0].start()]]
    for i, (match, render) in enumerate(resolved):
        end = resolved[i + 1][0].start() if i + 1 < len(resolved) else len(text)
        raw_args = text[match.end():end]
        # Keep the whitespace the user had before the next token so two
        # rendered instructions don't run together.
        trailing_ws = raw_args[len(raw_args.rstrip()):]
        pieces.append(render(raw_args.strip()) + trailing_ws)

    body = "".join(pieces)
    if len(resolved) == 1:
        return body
    return (
        "Perform the following in order, waiting for each step's result "
        f"before starting the next:\n{body}"
    )
