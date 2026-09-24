"""E2E tests for the delete-blocked-by-routine conflict Callout."""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e.pages import AgentsPage


@pytest.fixture
def blocking_routine(page: Page):
    """Create a profile + a routine whose task references it.

    Yields a dict with the IDs and the routine description so tests can
    assert on the conflict Callout content. Tears down both on exit so
    profiles list stays clean across tests.
    """
    profile_id = "test_pinned_target"
    routine_description = "E2E delete-conflict test routine"

    page.request.post("/api/profiles", data={
        "id": profile_id,
        "name": "Pinned Target",
        "description": "test profile pinned by a routine",
        "model": "",
        "skills": [],
    })

    # Routines have no HTTP create endpoint — seed via the running app's
    # tasks store. File-backed, so the next API read sees it.
    routine_id = container_exec(
        "from tasks import get_store\n"
        "s = get_store()\n"
        f"g = s.create_routine({routine_description!r})\n"
        f"s.create_task(g.id, 'blocking task', 'noop', agent_profile={profile_id!r})\n"
        "print(g.id)\n"
    )

    yield {
        "profile_id": profile_id,
        "routine_id": routine_id,
        "routine_description": routine_description,
    }

    # Routine first — so the profile is no longer pinned and the delete succeeds
    page.request.delete(f"/api/routines/{routine_id}")
    page.request.delete(f"/api/profiles/{profile_id}")


def test_delete_blocked_shows_conflict_callout(page: Page, blocking_routine):
    """Clicking Delete on a profile pinned by a routine shows the Callout
    listing the blocking routine and leaves the profile in the list."""
    agents = AgentsPage(page).goto()
    agents.profiles.select(blocking_routine["profile_id"])
    agents.builder.delete()

    expect(agents.builder.delete_conflict).to_be_visible()
    expect(agents.builder.delete_conflict).to_contain_text("Can't delete")
    expect(agents.builder.delete_conflict).to_contain_text(blocking_routine["routine_description"])

    # Profile must still be in the list — the delete was rejected
    agents.back()
    expect(agents.profiles.item(blocking_routine["profile_id"])).to_be_visible()


def test_dismiss_conflict_callout(page: Page, blocking_routine):
    """Clicking the × on the Callout removes it without affecting state."""
    agents = AgentsPage(page).goto()
    agents.profiles.select(blocking_routine["profile_id"])
    agents.builder.delete()
    expect(agents.builder.delete_conflict).to_be_visible()

    agents.builder.dismiss_delete_conflict()
    expect(agents.builder.delete_conflict).to_be_hidden()


def test_switching_profiles_clears_conflict(page: Page, blocking_routine):
    """Picking a different profile clears any stale conflict Callout."""
    agents = AgentsPage(page).goto()
    agents.profiles.select(blocking_routine["profile_id"])
    agents.builder.delete()
    expect(agents.builder.delete_conflict).to_be_visible()

    # Switch to Omnideck (always present — it's the default). In the list →
    # detail model you return to the list first, then open the other agent.
    agents.back()
    agents.profiles.select("omnideck")
    expect(agents.builder.delete_conflict).to_be_hidden()
