"""Generic MCP optional sign-in fields use the shared connection form layout."""

import re

import pytest
from playwright.sync_api import expect

from tests.e2e.pages.settings_page import SettingsPage


@pytest.mark.parametrize("width", [1280, 390])
def test_mcp_signin_fields_spacing_and_keyboard_disclosure(page, width):
    page.set_viewport_size({"width": width, "height": 900})
    flow = SettingsPage(page).goto_integrations().integrations.open_add_flow()
    flow.pick_provider("mcp").next_()
    summary = flow.root.locator("summary").filter(has_text="Sign-in settings")
    details = summary.locator("..")
    redirect = flow.root.get_by_label("Redirect URL", exact=False)
    expect(redirect).not_to_be_visible()
    summary.focus()
    summary.press("Enter")
    expect(redirect).to_be_visible()
    expect(details).to_have_attribute("open", "")

    # Check real browser geometry, including helper text, not just CSS classes.
    layout = details.evaluate("""element => {
        const bounds = element.getBoundingClientRect();
        const fields = [...element.querySelectorAll('label')].map(label => {
            const field = label.getBoundingClientRect();
            const input = label.querySelector('input').getBoundingClientRect();
            return {top: field.top, bottom: field.bottom, left: input.left, right: input.right};
        });
        return {left: bounds.left, right: bounds.right, fields,
            headingBottom: element.querySelector('summary').getBoundingClientRect().bottom};
    }""")
    assert len(layout["fields"]) == 4
    assert layout["fields"][0]["top"] - layout["headingBottom"] >= 12
    for field in layout["fields"]:
        assert field["left"] >= layout["left"] - 1
        assert field["right"] <= layout["right"] + 1
    for previous, current in zip(layout["fields"], layout["fields"][1:]):
        assert current["top"] - previous["bottom"] >= 16

    client = flow.root.get_by_label(re.compile(r"^Client ID"))
    client.fill("test-client")
    summary.focus()
    summary.press("Space")
    expect(client).not_to_be_visible()
    summary.press("Enter")
    expect(client).to_have_value("test-client")
    flow.root.get_by_role("button", name="Back", exact=True).click()
    flow.root.get_by_role("button", name="Cancel", exact=True).click()
