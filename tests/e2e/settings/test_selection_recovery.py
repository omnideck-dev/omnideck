"""Failure and sharing boundaries for the unified selection editors."""

import json
from pathlib import Path

from playwright.sync_api import expect

from tests.e2e.pages import AgentsPage, SettingsPage
from tests.e2e.settings.test_selection_navigation import selection_records  # noqa: F401


def test_failed_agent_save_retains_selections_for_retry(page, selection_records):
    """A failed save leaves the draft intact; retry persists the same choices."""
    skill_id, profile_id, _, category = selection_records
    agents = AgentsPage(page).goto()
    agents.profiles.select(profile_id)
    agents.builder.tools.add("Skills", "Selection workflow")
    agents.builder.tools.add("Integrations", "Selection account B")
    failed = []

    def unavailable_once(route):
        if route.request.method == "PUT" and not failed:
            failed.append(True)
            route.fulfill(status=503, json={"message": "Temporary save failure"})
        else:
            route.continue_()

    page.route(f"**/api/profiles/{profile_id}", unavailable_once)
    agents.builder.save()
    expect(agents.builder.save_error).to_be_visible()
    expect(agents.builder.tools.row("skill", skill_id)).to_be_visible()
    expect(agents.builder.tools.row("tool", category)).to_be_visible()
    stored = page.request.get(f"/api/profiles/{profile_id}").json()
    assert stored["skills"] == [] and stored["tool_categories"] == []
    agents.builder.save()
    expect(page.get_by_test_id("agent-detail").get_by_role("status")).to_have_text("Changes saved")
    expect(agents.builder.save_error).to_have_count(0)
    stored = page.request.get(f"/api/profiles/{profile_id}").json()
    assert stored["skills"] == [skill_id]
    assert stored["tool_categories"] == [category]


def test_unavailable_catalog_does_not_erase_saved_skill_selections(page, selection_records):
    """A metadata outage must not turn saving another edit into permission loss."""
    skill_id, _, _, category = selection_records
    page.route("**/api/tool-categories", lambda route: route.fulfill(status=503, json={"error": "unavailable"}))
    skills = SettingsPage(page).goto_skills().skills.select(skill_id)
    expect(skills.tools.row("tool", "memory")).to_be_visible()
    expect(skills.tools.row("tool", category)).to_have_count(0)
    skills.description_input.fill("Edited while catalog is unavailable")
    skills.save()
    expect(skills.item(skill_id)).to_contain_text("Edited while catalog is unavailable")
    stored = page.request.get(f"/api/skills/{skill_id}").json()
    assert stored["tool_categories"] == ["memory", category]
    page.unroute("**/api/tool-categories")
    SettingsPage(page).goto_skills().skills.select(skill_id)
    expect(skills.tools.row("tool", category)).to_contain_text("Selection account B")


def test_exported_skill_omits_local_connection_without_changing_original(page, selection_records):
    """The real download keeps built-ins but cannot transfer a local account ID."""
    skill_id, _, _, category = selection_records
    skills = SettingsPage(page).goto_skills().skills.select(skill_id)
    with page.expect_download() as download:
        skills.export_editor()
    exported = json.loads(Path(download.value.path()).read_text())
    assert exported["skills"][0]["tool_categories"] == ["memory"]
    assert category not in json.dumps(exported)
    assert page.request.get(f"/api/skills/{skill_id}").json()["tool_categories"] == ["memory", category]


def test_deleted_integration_cleans_assignments_and_stale_editor_saves(page, selection_records):
    """Real deletion cleans saved assignments and a retained draft cannot restore them."""
    skill_id, profile_id, connections, category = selection_records
    agents = AgentsPage(page).goto()
    agents.profiles.select(profile_id)
    agents.builder.tools.add("Skills", "Selection workflow")
    agents.builder.tools.add("Integrations", "Selection account B")
    agents.builder.save()
    expect(page.get_by_test_id("agent-detail").get_by_role("status")).to_have_text("Changes saved")
    stale_profile = page.request.get(f"/api/profiles/{profile_id}").json()

    settings = SettingsPage(page).goto_skills()
    skills = settings.skills.select(skill_id)
    skills.description_input.fill("Draft preserved across integration deletion")
    row = skills.tools.row("tool", category)
    row.get_by_role("button", name="Selection account B", exact=True).click()
    row.get_by_role("button", name="Manage in Integrations").click()
    tab = settings.integrations
    tab.open_connection_settings()
    tab.remove_button(connections[1]).click()
    with page.expect_response(lambda response: response.request.method == "DELETE"
                              and response.url.endswith(f"/api/integrations/{connections[1]}")) as deleted:
        page.get_by_role("button", name="Delete integration", exact=True).click()
    assert deleted.value.status == 204
    saved_agent = page.request.get(f"/api/profiles/{profile_id}").json()
    assert saved_agent["tool_categories"] == []
    assert saved_agent["skills"] == [skill_id]
    assert page.request.get(f"/api/skills/{skill_id}").json()["tool_categories"] == ["memory"]
    page.get_by_test_id("settings-tab-skills").click()
    expect(skills.description_input).to_have_value("Draft preserved across integration deletion")
    expect(skills.tools.row("tool", category)).to_have_count(0)
    expect(skills.tools.row("tool", "memory")).to_be_visible()
    expect(page.get_by_role("button", name="Integration", exact=True)).to_have_count(0)
    # This editor was mounted before deletion and still has its unsaved draft.
    skills.save()
    expect(skills.item(skill_id)).to_contain_text("Draft preserved across integration deletion")
    saved_skill = page.request.get(f"/api/skills/{skill_id}").json()
    assert saved_skill["tool_categories"] == ["memory"]
    assert saved_skill["description"] == "Draft preserved across integration deletion"
    # Another browser could submit an older agent snapshot after deletion too.
    stale_profile["description"] = "Edited from another tab"
    response = page.request.put(f"/api/profiles/{profile_id}", data=stale_profile)
    assert response.ok, response.text()
    assert response.json()["tool_categories"] == []
    assert response.json()["description"] == "Edited from another tab"

    agents.goto().profiles.select(profile_id)
    expect(agents.builder.tools.row("tool", category)).to_have_count(0)
    skill_row = agents.builder.tools.row("skill", skill_id)
    skill_row.get_by_role("button", name="Selection workflow", exact=True).click()
    expect(skill_row.get_by_role("region", name="Memory", exact=True)).to_be_visible()
    expect(skill_row.get_by_role("region", name="Integration", exact=True)).to_have_count(0)
    expect(skill_row.get_by_role("button", name="Manage in Integrations")).to_have_count(0)
