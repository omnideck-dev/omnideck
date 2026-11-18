"""Migration 017: Give the installed ``assistant`` skill the ``theme`` tools and their guidance.

Migration 006 copied the shipped ``assistant`` skill into ``{state}/skills/`` once and
never touches it again, so changes to the shipped record only reach fresh installs.
This brings an install that already has the skill level with what a fresh install gets:
the ``theme`` tool category, and the prompt paragraph that tells the agent how to use
``get_theme`` and ``set_theme``. Without that paragraph an agent has only the tool
descriptions to go on.

Only those two additions are made. Everything already in the record, including a prompt
the user has edited, is kept exactly as it was, and the paragraph is appended after it.
A skill the user deleted stays deleted, and a record that already has both is not
rewritten.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from skills._store import SKILLS_SUBDIR

logger = logging.getLogger(__name__)

_ASSISTANT_FILE = "assistant.json"
_CATEGORY = "theme"

# A snapshot of the paragraph shipped in the assistant skill when this migration was written.
# It is deliberately not read from the shipped record: a migration must keep doing the same
# thing after that record is edited again.
_THEME_GUIDANCE = (
    "THEME \u2014 use get_theme and set_theme only when the user asks to change the whole app's look "
    "(colors, fonts, light or dark mode); never for a single component. Call get_theme first and use "
    "the setting names it lists; never guess names. Set only what the user asked for: set_theme leaves "
    "every other setting as it is, and reset=true restores the defaults. A request for a whole look or "
    "palette means setting the backgrounds (canvas, surface, elevated), text and borders, not only the "
    "accent, and keeping text readable on the new backgrounds. Colors have separate light and dark "
    "values, so change both unless the user names one mode. Changes appear in the open app within moments."
)

# Present in any prompt that already explains the theme tools, whoever wrote it.
_GUIDANCE_MARKER = "set_theme"


def _append_paragraph(prompt: str, paragraph: str) -> str:
    """Add ``paragraph`` after ``prompt`` as its own paragraph, leaving ``prompt`` itself untouched."""
    if not prompt.strip():
        return paragraph
    if prompt.endswith("\n\n"):
        return prompt + paragraph
    return prompt + ("\n" if prompt.endswith("\n") else "\n\n") + paragraph


def migrate(state_dir: Path) -> None:
    """Add the ``theme`` category and its prompt guidance to the installed ``assistant`` skill."""
    path = state_dir / SKILLS_SUBDIR / _ASSISTANT_FILE
    if not path.exists():
        return

    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Unreadable %s, skipping migration 017", path)
        return
    if not isinstance(record, dict):
        logger.warning("Unexpected contents in %s, skipping migration 017", path)
        return

    added: list[str] = []

    categories = list(record.get("tool_categories") or [])
    if _CATEGORY not in categories:
        record["tool_categories"] = [*categories, _CATEGORY]
        added.append("the theme tool category")

    prompt = record.get("prompt")
    prompt = prompt if isinstance(prompt, str) else ""
    if _GUIDANCE_MARKER not in prompt:
        record["prompt"] = _append_paragraph(prompt, _THEME_GUIDANCE)
        added.append("the theme guidance")

    if not added:
        return
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    logger.info("Added %s to the assistant skill", " and ".join(added))
