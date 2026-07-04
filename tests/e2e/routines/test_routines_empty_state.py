"""E2E: the routines empty state seeds a new chat with the example prompt.

With no routines, the Routines view shows a full-screen prompt whose example, when
clicked, opens a fresh conversation with the composer pre-filled — exercising
the routines → chat hand-off and the draft-seeding timing.
"""

import re

from playwright.sync_api import Page, expect

from tests.e2e.pages import ChatView, RoutinesView


def _delete_all_routines(page: Page) -> None:
    for g in page.request.get("/api/routines").json().get("routines", []):
        page.request.delete(f"/api/routines/{g['id']}", fail_on_status_code=False)


def test_empty_state_seeds_new_chat(page: Page):
    _delete_all_routines(page)

    routines = RoutinesView(page).goto_empty()
    routines.empty_example().click()

    composer = ChatView(page).composer
    # Seeded as a "Create a routine that…" instruction so the agent sets up a
    # recurring routine rather than running the task once.
    expect(composer).to_have_value(re.compile("Create a routine that.*unread email"), timeout=5000)
