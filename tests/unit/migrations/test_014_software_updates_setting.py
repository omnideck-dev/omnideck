"""Tests for migration 014: the automatic software updates preference."""

import json

import pytest

from migrations._014_software_updates_setting import _KEY, migrate


@pytest.fixture()
def state_dir(tmp_path):
    """State directory root."""
    return tmp_path


@pytest.mark.unit
class TestMigration014:
    """Seeding of software_updates_automatic into settings.json."""

    def test_no_settings_file_is_noop(self, state_dir):
        """Install without a settings.json does nothing — defaults apply on read."""
        migrate(state_dir)
        assert not (state_dir / "settings.json").exists()

    def test_seeds_the_preference_switched_off(self, state_dir):
        """An install that predates the preference is not opted in by the migration."""
        path = state_dir / "settings.json"
        path.write_text(json.dumps({"setup_complete": True}))

        migrate(state_dir)

        assert json.loads(path.read_text())[_KEY] is False

    def test_an_existing_choice_is_left_alone(self, state_dir):
        """Someone who already turned it on does not get it turned back off."""
        path = state_dir / "settings.json"
        path.write_text(json.dumps({_KEY: True}))

        migrate(state_dir)

        assert json.loads(path.read_text())[_KEY] is True

    def test_other_settings_survive(self, state_dir):
        """Seeding one key rewrites the file, so the rest of it has to come back."""
        path = state_dir / "settings.json"
        path.write_text(json.dumps({"default_agent": "omnideck", "vision_think": True}))

        migrate(state_dir)

        data = json.loads(path.read_text())
        assert data["default_agent"] == "omnideck"
        assert data["vision_think"] is True

    def test_corrupt_file_is_left_alone(self, state_dir):
        """An unreadable settings file is not overwritten by this migration."""
        path = state_dir / "settings.json"
        path.write_text("{ not json")

        migrate(state_dir)

        assert path.read_text() == "{ not json"
