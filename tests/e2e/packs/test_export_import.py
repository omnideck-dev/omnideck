"""E2E tests for sharing: exporting and importing agents and skills.

Drives the real UI against the live backend. Exercises every export
permutation for an agent (skills on/off × provider·model on/off), verifies the
downloaded file carries the full profile — inference settings included, not
just the prompt/model — and imports packs back through the hidden file input,
asserting the new items appear and persist.
"""

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.pages import AgentsPage, SettingsPage

# Distinctive inference values so a round-trip can prove every setting travels,
# not just the headline fields (prompt / provider / model).
INFERENCE = {
    "temperature": 0.42,
    "top_k": 37,
    "top_p": 0.83,
    "repeat_penalty": 1.15,
    "num_predict": 1234,
    "think": True,
    "context_window": 8192,
    "max_iterations": 7,
    "reasoning_effort": "high",
    "compaction_threshold": 0.66,
}

# The INFERENCE keys tuned to a specific provider/model. These travel only when
# the provider and model do; the rest (max_iterations, compaction_threshold) are
# app-orchestration settings and always travel.
MODEL_BOUND_INFERENCE = (
    "temperature", "top_k", "top_p", "repeat_penalty",
    "num_predict", "think", "context_window", "reasoning_effort",
)


@pytest.fixture
def clean_stores(page: Page):
    """Delete any profiles/skills that didn't exist before the test.

    Covers both seeded records and anything an import creates (which lands with
    a fresh, unpredictable id).
    """
    before_p = {p["id"] for p in page.request.get("/api/profiles?include_disabled=true").json()}
    before_s = {s["id"] for s in page.request.get("/api/skills").json()}
    yield
    for p in page.request.get("/api/profiles?include_disabled=true").json():
        if p["id"] not in before_p:
            page.request.delete(f"/api/profiles/{p['id']}", fail_on_status_code=False)
    for s in page.request.get("/api/skills").json():
        if s["id"] not in before_s:
            page.request.delete(f"/api/skills/{s['id']}", fail_on_status_code=False)


def _seed_skill(page: Page, skill_id: str, name: str) -> None:
    page.request.post("/api/skills", data={
        "id": skill_id,
        "name": name,
        "description": f"{name} desc",
        "prompt": f"{name} prompt.",
        "tool_categories": ["coding"],
    })


def _seed_profile(page: Page, profile_id: str, name: str, *, skills: list[str]) -> None:
    page.request.post("/api/profiles", data={
        "id": profile_id,
        "name": name,
        "description": "sharing e2e",
        "provider": "ollama",
        "model": "test-model:7b",
        "system_prompt": "You are the seeded agent.",
        "skills": skills,
        **INFERENCE,
    })


def _download_json(page: Page, trigger) -> tuple[dict, str]:
    """Run ``trigger`` (which starts a download) and return (json, filename)."""
    with page.expect_download() as dl_info:
        trigger()
    download = dl_info.value
    data = json.loads(Path(download.path()).read_text(encoding="utf-8"))
    return data, download.suggested_filename


# ── Agent export permutations ─────────────────────────────────────────────

@pytest.mark.parametrize("include_skills", [True, False])
@pytest.mark.parametrize("include_model", [True, False])
def test_agent_export_permutations(page: Page, clean_stores, include_skills: bool, include_model: bool):
    """Every skills×model permutation: the system prompt and app-orchestration
    settings always travel; skills, provider·model, and the model-tuned inference
    settings appear only when their toggle is on."""
    _seed_skill(page, "e2e_share_skill", "E2E Share Skill")
    _seed_profile(page, "e2e_share_agent", "E2E Share Agent", skills=["e2e_share_skill"])

    agents = AgentsPage(page).goto()
    agents.profiles.export("e2e_share_agent")
    agents.set_export_include_skills(include_skills)
    agents.set_export_include_model(include_model)
    pack, filename = _download_json(page, agents.export_confirm.click)

    assert filename.endswith(".agent.omnideck.json")
    assert pack["kind"] == "omnideck.pack"
    prof = pack["profiles"][0]

    # Always present, regardless of toggles: the system prompt and the
    # app-orchestration settings that don't depend on a specific model.
    assert prof["system_prompt"] == "You are the seeded agent."
    for key, value in INFERENCE.items():
        if key not in MODEL_BOUND_INFERENCE:
            assert prof[key] == value, f"app setting {key} was dropped from the export"
    # The skill reference on the profile is preserved either way; only the
    # embedded skill records depend on the toggle.
    assert prof["skills"] == ["e2e_share_skill"]

    if include_model:
        assert prof["provider"] == "ollama"
        assert prof["model"] == "test-model:7b"
        # The model-tuned settings travel with the provider and model.
        for key in MODEL_BOUND_INFERENCE:
            assert prof[key] == INFERENCE[key], f"{key} should travel with the model"
    else:
        assert prof["provider"] == ""
        assert prof["model"] == ""
        # And are cleared when the model stays behind.
        for key in MODEL_BOUND_INFERENCE:
            assert prof[key] is None, f"{key} should be cleared when the model isn't included"

    if include_skills:
        assert [s["id"] for s in pack["skills"]] == ["e2e_share_skill"]
        assert pack["skills"][0]["prompt"] == "E2E Share Skill prompt."
        assert pack["skills"][0]["tool_categories"] == ["coding"]
    else:
        assert pack["skills"] == []


def test_agent_export_from_editor(page: Page, clean_stores):
    """The editor's Export button opens the same dialog and downloads."""
    _seed_profile(page, "e2e_editor_export", "E2E Editor Export", skills=[])

    agents = AgentsPage(page).goto()
    agents.profiles.select("e2e_editor_export")
    agents.builder.export()
    pack, filename = _download_json(page, agents.export_confirm.click)

    assert filename.endswith(".agent.omnideck.json")
    assert pack["profiles"][0]["name"] == "E2E Editor Export"


# ── Skill export ──────────────────────────────────────────────────────────

def test_skill_export_contains_all_fields(page: Page, clean_stores):
    """A skill export carries the record verbatim under a .skill.omnideck.json name."""
    _seed_skill(page, "e2e_only_skill", "E2E Only Skill")

    skills_page = SettingsPage(page).goto_skills().skills
    pack, filename = _download_json(page, lambda: skills_page.export_row("e2e_only_skill"))

    assert filename.endswith(".skill.omnideck.json")
    assert pack["profiles"] == []
    skill = pack["skills"][0]
    assert skill["name"] == "E2E Only Skill"
    assert skill["prompt"] == "E2E Only Skill prompt."
    assert skill["tool_categories"] == ["coding"]


# ── Import ────────────────────────────────────────────────────────────────

def _write_pack(tmp_path: Path, name: str, pack: dict) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(pack), encoding="utf-8")
    return str(path)


def test_import_agent_pack_creates_profile_and_skill(page: Page, clean_stores, tmp_path):
    """Importing an agent pack creates the profile with its settings and the
    embedded skill, and points the profile at the newly created skill."""
    pack = {
        "kind": "omnideck.pack",
        "version": 1,
        "profiles": [{
            "id": "orig_agent",
            "name": "Imported Agent",
            "system_prompt": "Imported prompt.",
            "provider": "ollama",
            "model": "test-model:7b",
            "skills": ["orig_skill"],
            **INFERENCE,
        }],
        "skills": [{
            "id": "orig_skill",
            "name": "Imported Skill",
            "description": "",
            "prompt": "Imported skill prompt.",
            "tool_categories": ["coding"],
        }],
    }
    path = _write_pack(tmp_path, "imported-agent.agent.omnideck.json", pack)

    agents = AgentsPage(page).goto()
    agents.import_file(path)

    expect(page.get_by_test_id("agents-list")).to_contain_text("Imported Agent")

    profiles = page.request.get("/api/profiles?include_disabled=true").json()
    created = next(p for p in profiles if p["name"] == "Imported Agent")
    assert created["id"] != "orig_agent"  # fresh id
    assert created["system_prompt"] == "Imported prompt."
    for key, value in INFERENCE.items():
        assert created[key] == value

    skills = page.request.get("/api/skills").json()
    imported_skill = next(s for s in skills if s["name"] == "Imported Skill")
    assert imported_skill["id"] != "orig_skill"
    # The profile reference was remapped onto the new skill id.
    assert created["skills"] == [imported_skill["id"]]


def test_import_skill_pack_creates_skill(page: Page, clean_stores, tmp_path):
    """Importing a skill pack creates the skill record."""
    pack = {
        "kind": "omnideck.pack",
        "version": 1,
        "skills": [{
            "id": "orig",
            "name": "Imported Solo Skill",
            "description": "solo",
            "prompt": "Solo prompt.",
            "tool_categories": ["coding"],
        }],
    }
    path = _write_pack(tmp_path, "imported-skill.skill.omnideck.json", pack)

    skills_page = SettingsPage(page).goto_skills().skills
    skills_page.import_file(path)

    expect(page.get_by_text("Imported Solo Skill")).to_be_visible()
    stored = page.request.get("/api/skills").json()
    created = next(s for s in stored if s["name"] == "Imported Solo Skill")
    assert created["id"] != "orig"
    assert created["prompt"] == "Solo prompt."


def test_agent_round_trip_export_then_import(page: Page, clean_stores):
    """Export an agent (with skills + model) through the UI, then import the
    downloaded file back — the copy lands as a distinct, complete agent."""
    _seed_skill(page, "rt_skill", "RT Skill")
    _seed_profile(page, "rt_agent", "RT Agent", skills=["rt_skill"])

    agents = AgentsPage(page).goto()
    agents.profiles.export("rt_agent")
    agents.set_export_include_skills(True)
    agents.set_export_include_model(True)
    with page.expect_download() as dl_info:
        agents.export_confirm.click()
    download = dl_info.value

    # Re-import the exact file the browser produced.
    agents.import_file(download.path())

    profiles = page.request.get("/api/profiles?include_disabled=true").json()
    copies = [p for p in profiles if p["name"].startswith("RT Agent")]
    # Original plus the imported copy (name de-duped to "RT Agent (imported)").
    assert len(copies) == 2
    imported = next(p for p in copies if p["id"] != "rt_agent")
    assert imported["system_prompt"] == "You are the seeded agent."
    for key, value in INFERENCE.items():
        assert imported[key] == value
