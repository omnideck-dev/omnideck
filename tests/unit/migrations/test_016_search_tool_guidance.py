"""Upgrade the shipped prompt while retaining user-owned configuration."""

import json
from pathlib import Path

import pytest

from migrations._016_search_tool_guidance import migrate

_FIXTURE = Path(__file__).parent / "fixtures" / "coder_before_search_tools.json"


@pytest.mark.parametrize("customized", [False, True])
def test_only_stock_prompt_is_updated_and_original_is_backed_up(tmp_path, customized):
    path = tmp_path / "skills" / "coder.json"
    path.parent.mkdir()
    record = json.loads(_FIXTURE.read_text())
    record["name"] = "My coder"
    record["tool_categories"] = ["coding", "custom_tools"]
    if customized:
        record["prompt"] += "\nUser's own search instructions."
    original = json.dumps(record)
    path.write_text(original)
    migrate(tmp_path)
    updated = json.loads(path.read_text())
    backup = tmp_path / ".backups/016_search_tool_guidance/skills/coder.json"
    if customized:
        assert path.read_text() == original and not backup.exists()
    else:
        assert "search_text" in updated["prompt"] and "find_files" in updated["prompt"]
        assert "Use grep" not in updated["prompt"]
        assert updated["name"] == record["name"] and updated["tool_categories"] == record["tool_categories"]
        assert backup.read_text() == original
        migrated = path.read_text()
        migrate(tmp_path)
        assert path.read_text() == migrated and backup.read_text() == original


def test_deleted_skill_stays_deleted(tmp_path):
    migrate(tmp_path)
    assert not (tmp_path / "skills").exists()
