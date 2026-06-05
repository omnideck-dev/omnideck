"""Skill record registry and persistence.

A SkillRecord is the stored form of a skill: prompt text plus the tool category ids
it grants — no live tool callables. Records are JSON files in the state folder,
one per id. ``id`` is the stable key referenced by profiles and conversations;
``name`` is the editable display field and must stay unique so the LLM-facing
``load_skill(name)`` is unambiguous.
"""

import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field

from config import load_config

logger = logging.getLogger(__name__)

SKILLS_SUBDIR = "skills"


class SkillRecord(BaseModel):
    """A stored, user-editable skill: a prompt plus the tool categories it grants."""

    id: str
    name: str
    description: str = ""
    prompt: str = ""
    tool_categories: list[str] = Field(default_factory=list)
    enabled: bool = True


def _skills_dir() -> Path:
    return Path(load_config().settings.home_dir) / SKILLS_SUBDIR


def _load_all() -> dict[str, SkillRecord]:
    """Load every skill record from disk, keyed by id. Bad files are skipped."""
    records: dict[str, SkillRecord] = {}
    d = _skills_dir()
    if not d.is_dir():
        return records
    for f in sorted(d.glob("*.json")):
        try:
            record = SkillRecord.model_validate(json.loads(f.read_text()))
            records[record.id] = record
        except Exception:
            logger.warning("Failed to load skill record %s", f.name)
    return records


def list_skill_records() -> list[SkillRecord]:
    """All skill records, sorted by name."""
    return sorted(_load_all().values(), key=lambda r: r.name)


def get_skill_record(skill_id: str) -> SkillRecord | None:
    """Look up a skill record by id, or None if unknown."""
    return _load_all().get(skill_id)


def save_skill_record(record: SkillRecord) -> SkillRecord:
    """Persist a skill record as ``{id}.json``.

    Rejects a name already used by a different record — renaming a record keeps
    its id, so reusing the same id is fine, but two records may not share a name.
    """
    for other in _load_all().values():
        if other.id != record.id and other.name == record.name:
            msg = f"skill name {record.name!r} is already in use"
            raise ValueError(msg)
    d = _skills_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{record.id}.json").write_text(json.dumps(record.model_dump(), indent=2))
    return record


def delete_skill_record(skill_id: str) -> bool:
    """Delete a skill record. Returns False if it didn't exist."""
    path = _skills_dir() / f"{skill_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


__all__ = [
    "SKILLS_SUBDIR",
    "SkillRecord",
    "delete_skill_record",
    "get_skill_record",
    "list_skill_records",
    "save_skill_record",
]
