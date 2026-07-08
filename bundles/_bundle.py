"""Export/import bundles for agent profiles and skills.

A bundle is a portable JSON document that carries one or more agent profiles
and/or skill records. It lets a user hand a profile (optionally with its
attached skills) or a bare skill to someone else, or move them between
installs.

Import is always additive: everything lands with a freshly generated id so an
import can never clobber an existing profile or skill. Skill names must stay
unique, so a colliding imported skill name is suffixed. When a profile bundle
also carries the profile's skills, the profile's skill references are rewritten
to point at the newly created skill ids.
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

logger = logging.getLogger(__name__)

BUNDLE_KIND = "omnideck.bundle"
BUNDLE_VERSION = 1


class Bundle(BaseModel):
    """A portable collection of agent profiles and/or skills.

    ``kind`` and ``version`` tag the document so an importer can reject files
    that aren't omnideck bundles or come from an incompatible future format.
    """

    kind: str = BUNDLE_KIND
    version: int = BUNDLE_VERSION
    profiles: list[AgentProfile] = Field(default_factory=list)
    skills: list[SkillRecord] = Field(default_factory=list)


class ImportSummary(BaseModel):
    """What an import created, after id remapping and name de-duplication."""

    profiles: list[AgentProfile] = Field(default_factory=list)
    skills: list[SkillRecord] = Field(default_factory=list)


def build_profile_bundle(
    profile_id: str,
    *,
    include_skills: bool,
    include_model: bool,
) -> Bundle:
    """Bundle a single profile, optionally with its attached skills.

    Args:
        profile_id: The profile to export.
        include_skills: When True, the profile's attached skill records are
            embedded so the profile arrives complete. Skills that no longer
            resolve are silently dropped.
        include_model: When False, the bound provider and model are cleared so
            the bundle can be imported on an install with a different setup.
            The system prompt and every other setting are always kept.

    Raises:
        KeyError: If the profile doesn't exist.
    """
    profile = get_agent_profile(profile_id)
    if profile is None:
        raise KeyError(profile_id)

    if not include_model:
        profile = profile.model_copy(update={"provider": "", "model": ""})

    skills: list[SkillRecord] = []
    if include_skills:
        for skill_id in profile.skills:
            record = get_skill_record(skill_id)
            if record is None:
                logger.warning(
                    "profile %r references unknown skill %r; omitting from bundle",
                    profile_id, skill_id,
                )
                continue
            skills.append(record)

    return Bundle(profiles=[profile], skills=skills)


def build_skill_bundle(skill_id: str) -> Bundle:
    """Bundle a single skill record.

    Raises:
        KeyError: If the skill doesn't exist.
    """
    record = get_skill_record(skill_id)
    if record is None:
        raise KeyError(skill_id)
    return Bundle(skills=[record])


def import_bundle(bundle: Bundle) -> ImportSummary:
    """Persist a bundle's profiles and skills as fresh copies.

    Skills are imported first so profile skill references can be rewritten to
    the new ids. Every item gets a new id; skill names are suffixed on
    collision to satisfy the unique-name rule.
    """
    if bundle.kind != BUNDLE_KIND:
        msg = f"unrecognized bundle kind {bundle.kind!r}"
        raise ValueError(msg)
    if bundle.version > BUNDLE_VERSION:
        msg = f"bundle version {bundle.version} is newer than supported ({BUNDLE_VERSION})"
        raise ValueError(msg)

    used_skill_names = {r.name for r in list_skill_records()}
    skill_id_map: dict[str, str] = {}
    imported_skills: list[SkillRecord] = []
    for record in bundle.skills:
        new_id = uuid4().hex[:12]
        new_name = _dedupe_name(record.name, used_skill_names)
        used_skill_names.add(new_name)
        saved = save_skill_record(record.model_copy(update={"id": new_id, "name": new_name}))
        skill_id_map[record.id] = new_id
        imported_skills.append(saved)

    used_profile_names = {p.name for p in list_agent_profiles(include_disabled=True)}
    imported_profiles: list[AgentProfile] = []
    for profile in bundle.profiles:
        new_id = uuid4().hex[:12]
        new_name = _dedupe_name(profile.name, used_profile_names)
        used_profile_names.add(new_name)
        # Point skill references at the freshly imported copies. A reference
        # whose skill wasn't in the bundle is kept as-is — it may already exist
        # on this install, and a dangling id is tolerated at resolve time.
        remapped = [skill_id_map.get(sid, sid) for sid in profile.skills]
        saved = save_agent_profile(
            profile.model_copy(update={"id": new_id, "name": new_name, "skills": remapped})
        )
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
    "BUNDLE_KIND",
    "BUNDLE_VERSION",
    "Bundle",
    "ImportSummary",
    "build_profile_bundle",
    "build_skill_bundle",
    "import_bundle",
]
