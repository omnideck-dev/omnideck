"""E2E tests for the Custom Tools tab inside Settings."""

import json
import re
import textwrap
from contextlib import contextmanager

from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e._protocol import call_tool, say
from tests.e2e.pages import ChatView, SettingsPage


def _seed_tools(tools: list[dict]) -> None:
    """Write a custom-tools registry.json into the container's home dir."""
    payload = json.dumps(tools)
    script = textwrap.dedent(f"""
        from pathlib import Path
        from config import load_config
        path = Path(load_config().settings.home_dir) / 'custom_tools' / 'registry.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text({payload!r}, encoding='utf-8')
    """)
    container_exec(script)


def _read_tools() -> list[dict]:
    """Read the custom-tools registry.json from inside the container."""
    script = textwrap.dedent("""
        from pathlib import Path
        from config import load_config
        path = Path(load_config().settings.home_dir) / 'custom_tools' / 'registry.json'
        if path.exists():
            print(path.read_text(encoding='utf-8'))
        else:
            print('[]')
    """)
    return json.loads(container_exec(script) or "[]")


def _tool(name: str, *, description: str = '', tool_type: str = 'program', language: str = 'bash') -> dict:
    """Build a minimal but valid CustomToolDefinition dict."""
    return {
        "id": f"id-{name}",
        "name": name,
        "description": description,
        "type": tool_type,
        "language": language,
        "command_template": "",
        "script_filename": None,
        "parameters": [],
        "dependencies": [],
        "tags": [],
        "created_at": "2026-05-23T00:00:00+00:00",
        "updated_at": "2026-05-23T00:00:00+00:00",
    }


@contextmanager
def _default_agent_with_custom_tools(page: Page):
    """Temporarily grant the default agent a skill backed by Custom Tools."""
    skill_id = "e2e_custom_tool_maker"
    settings = page.request.get("/api/settings").json()
    profile_id = settings["default_agent"]
    original_profile = page.request.get(f"/api/profiles/{profile_id}").json()

    page.request.delete(f"/api/skills/{skill_id}", fail_on_status_code=False)
    created = page.request.post("/api/skills", data={
        "id": skill_id,
        "name": "E2E Custom Tool Maker",
        "description": "Grants Custom Tools for one lifecycle test.",
        "prompt": "",
        "tool_categories": ["custom_tools"],
    })
    assert created.status == 201

    updated_profile = {
        **original_profile,
        "skills": [*original_profile.get("skills", []), skill_id],
    }
    try:
        assert page.request.put(
            f"/api/profiles/{profile_id}",
            data=updated_profile,
        ).ok
        yield
    finally:
        page.request.put(
            f"/api/profiles/{profile_id}",
            data=original_profile,
            fail_on_status_code=False,
        )
        page.request.delete(
            f"/api/skills/{skill_id}",
            fail_on_status_code=False,
        )


def _open_custom_tools(page: Page) -> SettingsPage:
    """Navigate to Settings → Custom Tools."""
    settings = SettingsPage(page).goto()
    page.get_by_test_id("settings-tab-tools").click()
    page.get_by_test_id("custom-tools-tab").wait_for(state="visible")
    return settings


def test_setting_immediately_toggles_custom_tools_tab(page: Page):
    """The user setting adds and removes the Custom Tools tab without a reload."""
    assert page.request.put(
        "/api/settings",
        data={"custom_tools_enabled": False},
    ).ok

    try:
        SettingsPage(page).goto_system()
        toggle = page.get_by_role("switch", name="Custom Tools")
        tools_tab = page.get_by_test_id("settings-tab-tools")
        expect(toggle).not_to_be_checked()
        expect(tools_tab).not_to_be_visible()

        with page.expect_response(
            lambda response: response.url.endswith("/api/settings")
            and response.request.method == "PUT"
        ) as enabled_response:
            page.get_by_test_id("custom-tools-toggle").click()
        assert enabled_response.value.ok
        expect(toggle).to_be_checked()
        expect(tools_tab).to_be_visible()

        page.get_by_test_id("settings-tab-skills").click()
        page.get_by_role("tab", name=re.compile("Tool Categories")).click()
        custom_tools_category = page.get_by_test_id("cat-row-custom_tools")
        expect(custom_tools_category).to_be_visible()
        expect(custom_tools_category).to_contain_text(
            "The agent can create, look up, and run reusable tools."
        )

        page.get_by_test_id("settings-tab-system").click()
        with page.expect_response(
            lambda response: response.url.endswith("/api/settings")
            and response.request.method == "PUT"
        ) as disabled_response:
            page.get_by_test_id("custom-tools-toggle").click()
        assert disabled_response.value.ok
        expect(toggle).not_to_be_checked()
        expect(tools_tab).not_to_be_visible()

        page.get_by_test_id("settings-tab-skills").click()
        page.get_by_role("tab", name=re.compile("Tool Categories")).click()
        expect(page.get_by_test_id("cat-row-coding")).to_be_visible()
        expect(custom_tools_category).not_to_be_visible()
    finally:
        # The E2E harness enables Custom Tools for the catalog tests below.
        assert page.request.put(
            "/api/settings",
            data={"custom_tools_enabled": True},
        ).ok


def test_renders_seeded_tools(page: Page):
    """The Custom Tools tab lists one row per seeded tool with name + description."""
    _seed_tools([
        _tool("fetch_page", description="Fetch a URL and return text", tool_type="program", language="python"),
        _tool("ls_home", description="List the home dir", tool_type="command", language="bash"),
    ])

    _open_custom_tools(page)
    rows = page.get_by_test_id("custom-tools-row")
    expect(rows).to_have_count(2)
    expect(page.get_by_text("fetch_page")).to_be_visible()
    expect(page.get_by_text("Fetch a URL and return text")).to_be_visible()
    expect(page.get_by_text("ls_home")).to_be_visible()


def test_badge_label_reflects_type_or_language(page: Page):
    """Command type renders 'cmd'; otherwise the language is the badge label."""
    _seed_tools([
        _tool("py_tool", tool_type="program", language="python"),
        _tool("bash_tool", tool_type="program", language="bash"),
        _tool("cmd_tool", tool_type="command", language="bash"),
    ])

    _open_custom_tools(page)
    expect(page.locator('[data-tool-name="py_tool"]')).to_contain_text("python")
    expect(page.locator('[data-tool-name="bash_tool"]')).to_contain_text("bash")
    # Command type wins over language
    expect(page.locator('[data-tool-name="cmd_tool"]')).to_contain_text("cmd")


def test_agent_created_tool_can_be_deleted(page: Page):
    """A tool created by the agent can be deleted from Settings and persistence."""
    _seed_tools([
        _tool("keep_me", description="Keep this tool"),
    ])

    try:
        with _default_agent_with_custom_tools(page):
            ChatView(page).goto().new_conversation().send(
                call_tool(
                    "create_custom_tool",
                    name="agent_echo",
                    description="Echo text from an agent-created command",
                    tool_type="command",
                    command_template="printf 'agent echo'",
                )
                + say("created")
            ).wait_streaming()

        assert {tool["name"] for tool in _read_tools()} == {"agent_echo", "keep_me"}

        _open_custom_tools(page)
        expect(page.get_by_test_id("custom-tools-row")).to_have_count(2)
        page.locator('[data-tool-name="agent_echo"]').get_by_test_id("custom-tools-delete").click()
        expect(page.get_by_test_id("custom-tools-row")).to_have_count(1)
        expect(page.locator('[data-tool-name="agent_echo"]')).to_have_count(0)

        assert {tool["name"] for tool in _read_tools()} == {"keep_me"}
    finally:
        _seed_tools([])


def test_empty_state(page: Page):
    """With no tools seeded, the empty state renders."""
    _seed_tools([])

    _open_custom_tools(page)
    expect(page.get_by_text("No custom tools defined.")).to_be_visible()
    expect(page.get_by_test_id("custom-tools-row")).to_have_count(0)
