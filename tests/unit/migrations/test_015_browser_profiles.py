import json

from migrations._015_browser_profiles import migrate


def test_migration_moves_browser_skill_to_agent_setting(tmp_path):
    profiles = tmp_path / "agent_profiles"
    profiles.mkdir()
    path = profiles / "research.json"
    path.write_text(
        json.dumps(
            {
                "id": "research",
                "name": "Research",
                "skills": ["browser", "coder"],
            }
        )
    )

    migrate(tmp_path)

    migrated = json.loads(path.read_text())
    assert migrated["skills"] == ["coder"]
    assert migrated["browser_profile_id"] == "default"
    assert (tmp_path / "browser" / "profiles" / "default" / "profile.json").exists()


def test_migration_gives_general_browser_access_without_old_skill(tmp_path):
    profiles = tmp_path / "agent_profiles"
    profiles.mkdir()
    path = profiles / "omnideck.json"
    path.write_text(json.dumps({"id": "omnideck", "name": "General", "skills": []}))

    migrate(tmp_path)

    migrated = json.loads(path.read_text())
    assert migrated["browser_profile_id"] == "default"


def test_migration_removes_legacy_browser_skill_record(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    legacy = skills / "browser.json"
    legacy.write_text("{}")

    migrate(tmp_path)

    assert not legacy.exists()


def test_migration_removes_stale_browser_skill_guidance(tmp_path):
    profiles = tmp_path / "agent_profiles"
    profiles.mkdir()
    path = profiles / "omnideck.json"
    path.write_text(
        json.dumps(
            {
                "id": "omnideck",
                "name": "General",
                "skills": [],
                "system_prompt": (
                    "SKILLS — load tools on demand or delegate to sub-agents:\n\n"
                    "- load_skill(name) — adds tools to YOUR context. Use for quick tasks\n"
                    '  where you want direct control (e.g. load "browser" to open one URL,\n'
                    '  load "coder" to edit a single file, load "routine_planner" to create\n'
                    "  autonomous routines).\n\n"
                    "- Load when the task is quick and you want to see results directly\n"
                    "  (open one URL, read one file, run one command)."
                ),
            }
        )
    )

    migrate(tmp_path)

    prompt = json.loads(path.read_text())["system_prompt"]
    assert "Do not load Browser as a skill" in prompt
    assert 'load "browser"' not in prompt
