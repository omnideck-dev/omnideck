"""The resolved Skill model.

A SkillRecord (the persisted form) resolves into a Skill: a prompt fragment plus
the live tool callables that its tool categories grant.
"""

from typing import Any

from pydantic import BaseModel, model_validator


class Skill(BaseModel):
    """A loadable bundle of tools and a prompt fragment — the resolved
    counterpart of a persisted SkillRecord.

    Attributes:
        id: Stable identifier (the SkillRecord id). Defaults to ``name`` when
            unset, so a skill whose name equals its slug gets the right id with
            no extra wiring.
        name: Unique display name; used in load_skill() calls.
        description: One-line description shown in the skill catalog.
        prompt: Prompt fragment injected when the skill is loaded.
        tools: Tool callables this skill grants. Typed ``list[Any]`` so pydantic
            doesn't introspect each callable's signature — ``Callable[..., Any]``
            triggers ``typing.get_type_hints``, which can deadlock on the import
            lock when a tool callable is constructed mid-import.
    """

    id: str = ""
    name: str
    description: str
    prompt: str
    tools: list[Any]

    model_config = {"arbitrary_types_allowed": True}

    @model_validator(mode="after")
    def _default_id_to_name(self) -> "Skill":
        if not self.id:
            self.id = self.name
        return self
