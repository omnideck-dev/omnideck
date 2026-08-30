"""Export/import packs for agent profiles and skills.

A pack is a portable JSON document that carries one or more agent profiles
and/or skill records. It lets a user hand a profile (optionally with its
attached skills) or a bare skill to someone else, or move them between
installs.

The pack is a shim over the on-disk records, not the records themselves. A
``PackedProfile``/``PackedSkill`` carries only the shareable content — never the
on-disk id, which is meaningless on another install. A packed profile embeds
its skills inline rather than referencing them by id, so a pack can only ever
point at a skill it actually contains. That is the whole point of the
export-without-skills option: leave the skills behind and the profile arrives
with none, instead of dangling references that silently re-attach to same-id
skills that happen to exist on the target.

Import is always additive: everything lands with a freshly generated id so an
import can never clobber an existing profile or skill. Skill names must stay
unique, so a colliding imported skill name is suffixed.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from pydantic import BaseModel, Field

from agents._agent_profiles import (
    AgentProfile,
    get_agent_profile,
    list_agent_profiles,
    save_agent_profile,
)
from sdk.skills._store import (
    SkillRecord,
    get_skill_record,
    list_skill_records,
    save_skill_record,
)
from sdk.skills._policy import grants_internal_tool_category, is_internal_skill

logger = logging.getLogger(__name__)

PACK_KIND = "omnideck.pack"
PACK_VERSION = 1

# Profile fields that only make sense next to the provider and model they were
# tuned for. Cleared from an export that leaves the provider and model behind,
# so the pack lands cleanly on an install with a different setup.
_MODEL_BOUND_FIELDS = (
    "temperature",
    "top_k",
    "top_p",
    "repeat_penalty",
    "num_predict",
    "think",
    "reasoning_effort",
    "reasoning_summary",
    "thinking_budget",
    "context_window",
)


class PackedSkill(BaseModel):
    """A skill as it travels in a pack: its shareable content, no on-disk id.

    Import mints a fresh id, so the stored id never rides along.
    """

    name: str
    description: str = ""
    prompt: str = ""
    tool_categories: list[str] = Field(default_factory=list)


class PackedProfile(BaseModel):
    """An agent profile as it travels in a pack: its shareable content plus the
    skills it carries.

    The bundled skills *are* the agent's skills. An agent packed without its
    skills carries an empty list and imports with no skills — the pack cannot
    reference a skill it doesn't contain, so nothing re-attaches on import.
    """

    name: str
    description: str = ""
    enabled: bool = True
    system_prompt: str = ""
    provider: str = ""
    model: str = ""
    allow_spawn: bool = True
    allow_load_skills: bool = True
    temperature: float | None = None
    top_k: int | None = None
    top_p: float | None = None
    repeat_penalty: float | None = None
    num_predict: int | None = None
    think: bool | None = None
    reasoning_effort: str | None = None
    reasoning_summary: str | None = None
    thinking_budget: str | None = None
    context_window: int | None = None
    compaction_threshold: float | None = None
    max_iterations: int | None = None
    skills: list[PackedSkill] = Field(default_factory=list)


class Pack(BaseModel):
    """A portable collection of agent profiles and/or skills.

    ``kind`` and ``version`` tag the document so an importer can reject files
    that aren't omnideck packs or come from an incompatible future format. A
    profile carries its own skills inline; the top-level ``skills`` list is for
    a pack that ships bare skills with no profile.
    """

    kind: str = PACK_KIND
    version: int = PACK_VERSION
    profiles: list[PackedProfile] = Field(default_factory=list)
    skills: list[PackedSkill] = Field(default_factory=list)


class ImportSummary(BaseModel):
    """What an import created, after id assignment and name de-duplication."""

    profiles: list[AgentProfile] = Field(default_factory=list)
    skills: list[SkillRecord] = Field(default_factory=list)


def _pack_skill(record: SkillRecord) -> PackedSkill:
    """Strip a stored skill down to its shareable content."""
    return PackedSkill(
        name=record.name,
        description=record.description,
        prompt=record.prompt,
        tool_categories=record.tool_categories,
    )


def _pack_profile(profile: AgentProfile, *, include_skills: bool, include_model: bool) -> PackedProfile:
    """Convert a stored profile into its packable form.

    When ``include_skills`` is False the skills are left behind entirely — no
    records and no references. When ``include_model`` is False the provider and
    model, and the sampling and reasoning settings tuned to them, are cleared.
    """
    packed_skills: list[PackedSkill] = []
    if include_skills:
        for skill_id in profile.skills:
            record = get_skill_record(skill_id)
            if record is None:
                logger.warning(
                    "profile %r references unknown skill %r; omitting from pack",
                    profile.id,
                    skill_id,
                )
                continue
            if is_internal_skill(record.id) or grants_internal_tool_category(record.tool_categories):
                logger.warning(
                    "profile %r references application-managed skill %r; omitting from pack",
                    profile.id,
                    skill_id,
                )
                continue
            packed_skills.append(_pack_skill(record))

    # Browser grants and profile ids are local security policy. They never
    # travel with an exported agent, even if a future PackedProfile model adds
    # fields with similar names.
    data = profile.model_dump(exclude={"id", "skills", "browser_access", "browser_profile_id"})
    if not include_model:
        data["provider"] = ""
        data["model"] = ""
        data.update(dict.fromkeys(_MODEL_BOUND_FIELDS))
    return PackedProfile(**data, skills=packed_skills)


def build_profile_pack(
    profile_id: str,
    *,
    include_skills: bool,
    include_model: bool,
) -> Pack:
    """Pack a single profile, optionally with its attached skills.

    Args:
        profile_id: The profile to export.
        include_skills: When True, the profile's attached skill records are
            embedded so the profile arrives complete. Skills that no longer
            resolve are silently dropped. When False the profile arrives with
            no skills at all.
        include_model: When False, the provider and model, and the sampling and
            reasoning settings tuned to them, are cleared so the pack imports
            cleanly on an install with a different setup. The system prompt,
            skills, and remaining settings are always kept.

    Raises:
        KeyError: If the profile doesn't exist.
    """
    profile = get_agent_profile(profile_id)
    if profile is None:
        raise KeyError(profile_id)
    packed = _pack_profile(profile, include_skills=include_skills, include_model=include_model)
    return Pack(profiles=[packed])


def build_skill_pack(skill_id: str) -> Pack:
    """Pack a single skill record.

    Raises:
        KeyError: If the skill doesn't exist.
    """
    record = get_skill_record(skill_id)
    if record is None or is_internal_skill(record.id) or grants_internal_tool_category(record.tool_categories):
        raise KeyError(skill_id)
    return Pack(skills=[_pack_skill(record)])


def _import_skill(packed: PackedSkill, used_names: set[str]) -> SkillRecord:
    """Persist a packed skill as a fresh record, de-duplicating its name."""
    if grants_internal_tool_category(packed.tool_categories):
        raise ValueError("Browser access is configured on the agent and cannot be imported as a skill.")
    new_name = _dedupe_name(packed.name, used_names)
    used_names.add(new_name)
    return save_skill_record(
        SkillRecord(
            id=uuid4().hex[:12],
            name=new_name,
            description=packed.description,
            prompt=packed.prompt,
            tool_categories=packed.tool_categories,
        )
    )


def import_pack(pack: Pack) -> ImportSummary:
    """Persist a pack's profiles and skills as fresh copies.

    Raises:
        ValueError: If the pack's kind or version is unsupported, or it
            carries neither a profile nor a skill.
    """
    if pack.kind != PACK_KIND:
        raise ValueError("This file isn't an omnideck pack.")
    if pack.version > PACK_VERSION:
        raise ValueError(
            "This pack was made by a newer version of omnideck. Update omnideck, then try importing it again."
        )
    if not pack.profiles and not pack.skills:
        raise ValueError("This pack has no agents or skills to import.")

    # Validate every skill before writing anything so one invalid bundled skill
    # cannot leave a partially imported pack behind.
    packed_skills = [
        *pack.skills,
        *(skill for profile in pack.profiles for skill in profile.skills),
    ]
    if any(grants_internal_tool_category(skill.tool_categories) for skill in packed_skills):
        raise ValueError("Browser access is configured on the agent and cannot be imported as a skill.")

    used_skill_names = {r.name for r in list_skill_records()}
    imported_skills: list[SkillRecord] = [_import_skill(packed, used_skill_names) for packed in pack.skills]

    used_profile_names = {p.name for p in list_agent_profiles(include_disabled=True)}
    imported_profiles: list[AgentProfile] = []
    for packed_profile in pack.profiles:
        # Each profile's bundled skills become fresh records; the new profile
        # points at those new ids.
        skill_ids: list[str] = []
        for packed_skill in packed_profile.skills:
            record = _import_skill(packed_skill, used_skill_names)
            imported_skills.append(record)
            skill_ids.append(record.id)

        new_name = _dedupe_name(packed_profile.name, used_profile_names)
        used_profile_names.add(new_name)
        data = packed_profile.model_dump(exclude={"skills"})
        data["name"] = new_name
        saved = save_agent_profile(AgentProfile(id=uuid4().hex[:12], skills=skill_ids, **data))
        imported_profiles.append(saved)

    return ImportSummary(profiles=imported_profiles, skills=imported_skills)


def _dedupe_name(name: str, taken: set[str]) -> str:
    """Return ``name`` unchanged, or with an ``(imported)`` / numeric suffix if taken."""
    if name not in taken:
        return name
    candidate = f"{name} (imported)"
    if candidate not in taken:
        return candidate
    n = 2
    while f"{name} (imported {n})" in taken:
        n += 1
    return f"{name} (imported {n})"


__all__ = [
    "PACK_KIND",
    "PACK_VERSION",
    "ImportSummary",
    "Pack",
    "PackedProfile",
    "PackedSkill",
    "build_profile_pack",
    "build_skill_pack",
    "import_pack",
]
