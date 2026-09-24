"""Migration 015: move browser access from skills to agent configuration."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def migrate(state_dir: Path) -> None:
    """Move Browser access to one profile selection and create Default."""
    profiles_dir = state_dir / "agent_profiles"
    if profiles_dir.is_dir():
        for path in profiles_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.warning("Could not migrate browser settings in %s", path)
                continue

            skills = list(data.get("skills", []))
            had_browser_skill = "browser" in skills
            if had_browser_skill:
                data["skills"] = [skill for skill in skills if skill != "browser"]

            if "browser_profile_id" not in data:
                data["browser_profile_id"] = "default" if had_browser_skill or data.get("id") == "omnideck" else None

            prompt = data.get("system_prompt")
            if data.get("id") == "omnideck" and isinstance(prompt, str):
                if "Do not load Browser as a skill" not in prompt:
                    prompt = prompt.replace(
                        "SKILLS — load tools on demand or delegate to sub-agents:\n\n",
                        "SKILLS — load tools on demand or delegate to sub-agents:\n\n"
                        "Browser access, when enabled, is already available. Do not load "
                        "Browser as a skill.\n\n",
                    )
                prompt = prompt.replace(
                    '  where you want direct control (e.g. load "browser" to open one URL,\n'
                    '  load "coder" to edit a single file, load "routine_planner" to create\n',
                    '  where you want direct control (e.g. load "coder" to edit a single file,\n'
                    '  or load "routine_planner" to create\n',
                )
                prompt = prompt.replace(
                    "  (open one URL, read one file, run one command).",
                    "  (read one file, run one command, or plan a routine).",
                )
                data["system_prompt"] = prompt

            path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # Browser is now an explicit agent capability rather than an editable or
    # loadable skill. Remove the former seeded record if migration 006 copied it.
    legacy_browser_skill = state_dir / "skills" / "browser.json"
    if legacy_browser_skill.exists():
        legacy_browser_skill.unlink()

    # Preserve browser/profiles/default/storage_state.json from the former
    # implicit-persistence implementation and add metadata beside it.
    from browser.profile_store import BrowserProfileStore

    BrowserProfileStore(state_dir / "browser" / "profiles").ensure_default()
