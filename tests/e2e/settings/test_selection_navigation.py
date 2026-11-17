"""Real saved selections and approval navigation across both editors."""

import pytest
from playwright.sync_api import expect

from tests.e2e.pages import AgentsPage, SettingsPage


@pytest.fixture
def selection_records(page):
    connections = []
    skill_id, profile_id = "selection-navigation-skill", "selection-navigation-agent"
    try:
        for label in ("Selection account A", "Selection account B"):
            response = page.request.post("/api/integrations", data={
                "slug": "test", "label": label,
                "auth_blob": {"token": "omnideck-test-token"},
                "operation_grants": ["test.value.get"],
            })
            assert response.ok, response.text()
            connections.append(response.json()["id"])
        category = f"integration:{connections[1]}"
        response = page.request.post("/api/skills", data={
            "id": skill_id, "name": "Selection workflow", "prompt": "Use selected tools.",
            "tool_categories": ["memory", category],
        })
        assert response.ok, response.text()
        response = page.request.post("/api/profiles", data={
            "id": profile_id, "name": "Selection agent", "model": "",
            "skills": [], "tool_categories": [],
        })
        assert response.ok, response.text()
        yield skill_id, profile_id, connections, category
    finally:
        page.request.delete(f"/api/profiles/{profile_id}")
        page.request.delete(f"/api/skills/{skill_id}")
        for connection in connections:
            page.request.delete(f"/api/integrations/{connection}")


def test_agent_selection_save_reload_remove_and_edit_skill(page, selection_records):
    """All three kinds persist; removing a direct group leaves its skill intact."""
    skill_id, profile_id, connections, category = selection_records
    agents = AgentsPage(page).goto()
    agents.profiles.select(profile_id)
    selection = agents.builder.tools
    selection.open()
    search = selection.picker.get_by_role("searchbox")
    search.fill("account B")
    expect(selection.option("Integrations", "Selection account B")).to_be_visible()
    expect(selection.option("Integrations", "Selection account A")).to_have_count(0)
    selection.option("Integrations", "Selection account B").click()
    selection.add("Built-in tools", "Memory")
    selection.add("Skills", "Selection workflow")
    # Selected entries are excluded; adding a skill doesn't duplicate its groups.
    selection.open()
    expect(selection.option("Skills", "Selection workflow")).to_have_count(0)
    expect(selection.option("Integrations", "Selection account B")).to_have_count(0)
    page.keyboard.press("Escape")
    agents.builder.save()
    expect(page.get_by_test_id("agent-detail").get_by_role("status")).to_have_text("Changes saved")
    saved = page.request.get(f"/api/profiles/{profile_id}").json()
    assert saved["skills"] == [skill_id]
    assert saved["tool_categories"] == [category, "memory"]
    agents.goto().profiles.select(profile_id)
    expect(selection.row("skill", skill_id)).to_be_visible()
    expect(selection.row("tool", category)).to_be_visible()
    selection.row("tool", "memory").get_by_role("button", name="Remove Memory", exact=True).click()
    agents.builder.save()
    expect(page.get_by_test_id("agent-detail").get_by_role("status")).to_have_text("Changes saved")
    saved = page.request.get(f"/api/profiles/{profile_id}").json()
    assert saved["skills"] == [skill_id]
    assert saved["tool_categories"] == [category]
    skill = selection.row("skill", skill_id)
    skill.get_by_role("button", name="Selection workflow", exact=True).click()
    expect(skill.get_by_role("region", name="Memory", exact=True)).to_be_visible()
    skill.get_by_role("button", name="Edit skill", exact=True).click()
    expect(page.get_by_test_id("skill-name-input")).to_have_value("Selection workflow")


def test_skill_draft_survives_exact_integration_link_and_approval_refresh(page, selection_records):
    """The link targets account B, preserves a draft, and shows revoked approvals."""
    skill_id, _, connections, category = selection_records
    settings = SettingsPage(page).goto_skills()
    skills = settings.skills.select(skill_id)
    skills.name_input.fill("Unsaved workflow name")
    row = skills.tools.row("tool", category)
    row.get_by_role("button", name="Selection account B", exact=True).click()
    expect(row).to_contain_text("1 tools selected in Integrations")
    row.get_by_role("button", name="Manage in Integrations").click()
    tab = settings.integrations
    expect(tab.change_tools_button(connections[1])).to_be_visible()
    expect(tab.change_tools_button(connections[0])).to_have_count(0)
    tab.change_tools_button(connections[1]).click()
    tab.tool_checkbox("test.value.get").click()
    tab.save_and_wait(connections[1])
    page.get_by_test_id("settings-tab-skills").click()
    expect(skills.name_input).to_have_value("Unsaved workflow name")
    expect(row).to_contain_text("0 tools selected in Integrations")
    expect(row.get_by_text("No tools available.", exact=True)).to_be_visible()
    # Approval changes update details, never overwrite saved or draft selections.
    saved = page.request.get(f"/api/skills/{skill_id}").json()
    assert saved["name"] == "Selection workflow"
    assert saved["tool_categories"] == ["memory", category]
    skills.save()
    expect(skills.item(skill_id)).to_contain_text("Unsaved workflow name")
    settings.goto_skills().skills.select(skill_id)
    expect(skills.name_input).to_have_value("Unsaved workflow name")
    expect(skills.tools.row("tool", category)).to_be_visible()
