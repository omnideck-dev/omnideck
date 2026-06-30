"""E2E: the goals empty state seeds a new chat with the example prompt.

With no goals, the Goals view shows a full-screen prompt whose example, when
clicked, opens a fresh conversation with the composer pre-filled — exercising
the goals → chat hand-off and the draft-seeding timing.
"""

import re

from playwright.sync_api import Page, expect

from tests.e2e.pages import ChatView, GoalsView


def _delete_all_goals(page: Page) -> None:
    for g in page.request.get("/api/goals").json().get("goals", []):
        page.request.delete(f"/api/goals/{g['id']}", fail_on_status_code=False)


def test_empty_state_seeds_new_chat(page: Page):
    _delete_all_goals(page)

    goals = GoalsView(page).goto_empty()
    goals.empty_example().click()

    composer = ChatView(page).composer
    # Seeded as a "Create a goal that…" instruction so the agent sets up a
    # recurring goal rather than running the task once.
    expect(composer).to_have_value(re.compile("Create a goal that.*unread email"), timeout=5000)
