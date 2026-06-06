"""E2E tests for the Skills tab inside Settings.

Drives the real UI against the live backend: seeds/reads the skill store in the
container, exercises the My Skills master-detail (create/rename/delete, plus the
duplicate-name guard) and the Tool Categories catalog.
"""

import json
import textwrap

from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e.pages import SettingsPage


def _seed_skills(skills: list[dict]) -> None:
    """Replace the container's skill store with exactly these records."""
    payload = json.dumps(skills)
    script = textwrap.dedent(f"""
        import json, shutil
        from pathlib import Path
        from config import load_config
        d = Path(load_config().settings.home_dir) / 'skills'
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)
        for rec in json.loads({payload!r}):
            (d / (rec['id'] + '.json')).write_text(json.dumps(rec), encoding='utf-8')
    """)
    container_exec(script)


def _read_skills() -> list[dict]:
    """Read every skill record JSON from inside the container."""
    script = textwrap.dedent("""
        import json
        from pathlib import Path
        from config import load_config
        d = Path(load_config().settings.home_dir) / 'skills'
        out = []
        if d.exists():
            for p in sorted(d.glob('*.json')):
                try:
                    out.append(json.loads(p.read_text(encoding='utf-8')))
                except Exception:
                    pass
        print(json.dumps(out))
    """)
    return json.loads(container_exec(script) or "[]")


def _skill(skill_id: str, *, name: str | None = None, description: str = "",
           prompt: str = "", tool_categories: list[str] | None = None) -> dict:
    """A minimal SkillRecord dict."""
    return {
        "id": skill_id,
        "name": name or skill_id,
        "description": description,
        "prompt": prompt,
        "tool_categories": tool_categories or [],
    }


def test_renders_seeded_skills(page: Page):
    """The Skills list shows one row per stored skill with its meta line."""
    _seed_skills([
        _skill("coder", name="Coder", description="Edit code", tool_categories=["coding"]),
        _skill("mailer", name="Mailer", description="Email helper", tool_categories=["email"]),
    ])

    skills = SettingsPage(page).goto_skills().skills
    expect(skills.item("coder")).to_be_visible()
    expect(skills.item("mailer")).to_be_visible()
    expect(skills.item("coder")).to_contain_text("category")


def test_create_skill_persists_to_store(page: Page):
    """Creating a skill via the UI writes a record with the granted category."""
    _seed_skills([])

    skills = SettingsPage(page).goto_skills().skills
    skills.new()
    skills.name_input.fill("E2E Coder")
    skills.description_input.fill("Created by e2e")
    skills.prompt.fill("Write good code.")
    skills.category_chip("coding").click()
    skills.save()

    expect(page.get_by_text("E2E Coder")).to_be_visible()

    stored = _read_skills()
    created = next(s for s in stored if s["name"] == "E2E Coder")
    assert created["prompt"] == "Write good code."
    assert created["tool_categories"] == ["coding"]
    assert created["id"]  # server-generated, non-empty


def test_rename_keeps_id(page: Page):
    """Renaming a skill updates the record in place under the same id."""
    _seed_skills([_skill("coder", name="Coder", tool_categories=["coding"])])

    skills = SettingsPage(page).goto_skills().skills
    skills.select("coder")
    expect(skills.name_input).to_have_value("Coder")
    skills.name_input.fill("Coder Renamed")
    skills.save()

    expect(page.get_by_text("Coder Renamed")).to_be_visible()
    stored = _read_skills()
    assert [s["id"] for s in stored] == ["coder"]
    assert stored[0]["name"] == "Coder Renamed"


def test_delete_removes_row_and_record(page: Page):
    """Deleting a skill removes its row and its stored record."""
    _seed_skills([
        _skill("coder", name="Coder", tool_categories=["coding"]),
        _skill("mailer", name="Mailer", tool_categories=["email"]),
    ])

    skills = SettingsPage(page).goto_skills().skills
    skills.select("coder")
    skills.delete()

    expect(skills.item("coder")).not_to_be_visible()
    names = {s["name"] for s in _read_skills()}
    assert "Coder" not in names
    assert "Mailer" in names


def test_duplicate_name_is_rejected(page: Page):
    """Saving a new skill with an existing name surfaces an error and doesn't persist."""
    _seed_skills([_skill("coder", name="Coder", tool_categories=["coding"])])

    skills = SettingsPage(page).goto_skills().skills
    skills.new()
    skills.name_input.fill("Coder")
    skills.save()

    expect(skills.save_error).to_be_visible()
    assert sum(1 for s in _read_skills() if s["name"] == "Coder") == 1


def test_categories_view_expands_to_tools(page: Page):
    """The Tool Categories view lists categories and expands a row to its tools."""
    _seed_skills([_skill("coder", name="Coder", tool_categories=["coding"])])

    skills = SettingsPage(page).goto_skills().skills
    skills.view_categories()

    expect(skills.category_row("coding")).to_be_visible()
    expect(skills.category_tools("coding")).not_to_be_visible()
    skills.category_row("coding").click()
    expect(skills.category_tools("coding")).to_be_visible()
    expect(skills.category_tools("coding")).to_contain_text("read_file")
