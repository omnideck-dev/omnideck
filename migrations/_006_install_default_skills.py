"""Migration 006: Install default skills and grant ``assistant`` to profiles.

Copies the shipped starter skill records to ``{state}/skills/`` (skipping any
that already exist), then appends the ``assistant`` skill to every existing
profile. Tools used to be global (integrations) or hard-wired onto the
interactive agent (memory); the ``assistant`` skill grants those tool categories,
so moving to skill-scoped tools doesn't silently strip them from any agent.

The grant makes no assumption about which profiles exist or how they're
configured — it just appends ``assistant`` wherever it isn't already present.
Fresh-install skill defaults belong in the shipped profile JSON, not here.

A seed, not a transform: a starter the user later deletes stays deleted, because
the migration is marked applied and never runs again.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from agents._agent_profiles import PROFILES_SUBDIR
from skills._store import SKILLS_SUBDIR

logger = logging.getLogger(__name__)

_DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent.parent / "sdk" / "skills" / "default_skills"
_ASSISTANT = "assistant"


def migrate(state_dir: Path) -> None:
    """Install the starter skills and grant ``assistant`` to existing profiles."""
    _install_default_skills(state_dir)
    _grant_assistant_to_profiles(state_dir)


def _install_default_skills(state_dir: Path) -> None:
    if not _DEFAULT_SKILLS_DIR.is_dir():
        logger.warning("Default skills directory not found: %s", _DEFAULT_SKILLS_DIR)
        return
    dest = state_dir / SKILLS_SUBDIR
    dest.mkdir(parents=True, exist_ok=True)
    installed = 0
    for src in _DEFAULT_SKILLS_DIR.glob("*.json"):
        dst = dest / src.name
        if dst.exists():
            continue
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        installed += 1
        logger.info("Installed default skill: %s", src.stem)
    logger.info("Installed %d default skill(s)", installed)


def _grant_assistant_to_profiles(state_dir: Path) -> None:
    profiles_dir = state_dir / PROFILES_SUBDIR
    if not profiles_dir.is_dir():
        return
    for path in sorted(profiles_dir.glob("*.json")):
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Skipping unreadable profile %s", path.name)
            continue
        skills = list(profile.get("skills") or [])
        if _ASSISTANT in skills:
            continue
        profile["skills"] = [*skills, _ASSISTANT]
        path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
        logger.info("Granted %s to profile %s", _ASSISTANT, profile.get("id"))
