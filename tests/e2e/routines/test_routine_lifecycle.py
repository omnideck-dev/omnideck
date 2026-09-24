"""E2E test for routine pause/resume lifecycle.

Seeds a routine via container_exec, opens the Routines panel, and verifies
that the Pause and Resume buttons toggle the routine's status correctly.
Also verifies the routine can be deleted via the ConfirmButton two-click
pattern.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e.pages import RoutinesView


ROUTINE_DESCRIPTION = "E2E lifecycle test routine"


@pytest.fixture
def test_routine(page: Page):
    """Seed a routine with one noop task. Tears down on exit."""
    # Clean up any stale routines with the same description from prior runs.
    existing = page.request.get("/api/routines").json().get("routines", [])
    for g in existing:
        if g["description"] == ROUTINE_DESCRIPTION:
            page.request.delete(f"/api/routines/{g['id']}", fail_on_status_code=False)

    routine_id = container_exec(
        "from tasks import get_store\n"
        "s = get_store()\n"
        f"g = s.create_routine({ROUTINE_DESCRIPTION!r}, auto_run=False)\n"
        "s.create_task(g.id, 'lifecycle task', 'noop')\n"
        "print(g.id)\n"
    )
    yield routine_id
    page.request.delete(f"/api/routines/{routine_id}", fail_on_status_code=False)


def test_pause_and_resume_routine(page: Page, test_routine):
    """Pause an active routine via the UI, verify status changes, then resume."""
    routines = RoutinesView(page).goto()
    routines.select_by_name(ROUTINE_DESCRIPTION)

    expect(routines.status_label()).to_contain_text("ACTIVE", timeout=5000)
    expect(routines.pause_button()).to_be_visible()

    routines.pause_button().click()
    expect(routines.status_label()).to_contain_text("PAUSED", timeout=5000)
    expect(routines.resume_button()).to_be_visible()

    resp = page.request.get(f"/api/routines/{test_routine}")
    assert resp.json()["routine"]["status"] == "paused"

    routines.resume_button().click()
    expect(routines.status_label()).to_contain_text("ACTIVE", timeout=5000)
    expect(routines.pause_button()).to_be_visible()

    resp = page.request.get(f"/api/routines/{test_routine}")
    assert resp.json()["routine"]["status"] == "active"


def test_delete_routine(page: Page, test_routine):
    """Delete a routine via the two-click ConfirmButton and verify it's gone."""
    routines = RoutinesView(page).goto()
    routines.select_by_name(ROUTINE_DESCRIPTION)
    expect(routines.status_label()).to_be_visible(timeout=5000)

    routines.delete_button().click()
    routines.confirm_button().click()
    page.wait_for_timeout(500)

    resp = page.request.get("/api/routines")
    all_routines = resp.json().get("routines", [])
    assert not any(g["id"] == test_routine for g in all_routines)


def test_delete_routine_inline_from_list(page: Page, test_routine):
    """Delete a routine from its list row (two-click) without opening the detail."""
    routines = RoutinesView(page).goto()
    expect(page.get_by_text(ROUTINE_DESCRIPTION, exact=True)).to_be_visible(timeout=5000)

    routines.delete_from_list(ROUTINE_DESCRIPTION)
    page.wait_for_timeout(500)

    resp = page.request.get("/api/routines")
    all_routines = resp.json().get("routines", [])
    assert not any(g["id"] == test_routine for g in all_routines)
