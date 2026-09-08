"""Update only the unchanged bundled coder prompt after replacing grep."""

import hashlib
import json
import logging
from pathlib import Path

from migrations._backup import backup_file

logger = logging.getLogger(__name__)
_OLD_PROMPT_SHA256 = "127bf918f52746fe951f46aaa73ec3622127348aa75124b028ff607ea0be25c8"
_DEFAULT = Path(__file__).resolve().parent.parent / "agent_core/skills/default_skills/coder.json"


def migrate(state_dir: Path) -> None:
    """Refresh stock search instructions without replacing user customization."""
    path = state_dir / "skills" / "coder.json"
    if not path.exists():
        return
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("Skipping unreadable coder skill during search-tool guidance migration")
        return
    if not isinstance(record, dict) or not isinstance(record.get("prompt"), str):
        return
    if hashlib.sha256(record["prompt"].encode()).hexdigest() != _OLD_PROMPT_SHA256:
        return
    prompt = json.loads(_DEFAULT.read_text(encoding="utf-8"))["prompt"]
    backup_file(state_dir, "016_search_tool_guidance", path)
    record["prompt"] = prompt
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
