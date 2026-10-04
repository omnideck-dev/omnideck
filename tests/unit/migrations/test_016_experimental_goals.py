import json

from migrations._016_experimental_goals import migrate


def test_seeds_goals_off_without_changing_existing_settings(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"setup_complete": True}))
    migrate(tmp_path)
    assert json.loads(path.read_text()) == {"setup_complete": True, "goals_enabled": False}


def test_preserves_explicit_experiment_choice_and_is_idempotent(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"goals_enabled": True}))
    migrate(tmp_path)
    migrate(tmp_path)
    assert json.loads(path.read_text()) == {"goals_enabled": True}


def test_fresh_install_needs_no_settings_file(tmp_path):
    migrate(tmp_path)
    assert not (tmp_path / "settings.json").exists()
