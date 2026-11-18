"""Deleting, archiving and restoring a chat that has a goal."""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._protocol import bash, say
from tests.e2e.pages.goals_view import goal_conversation, read_goal


@pytest.fixture
def goal_ui(page: Page):
    with goal_conversation(page) as view:
        yield view


def test_delete_of_a_working_goal_chat_asks_to_pause_first(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    view.composer.fill(read_goal() + bash('sleep 8') + say('Checked every venue.'))
    page.get_by_role('button', name='Send message', exact=True).click()
    expect(page.get_by_test_id('chat-stop-btn')).to_be_visible(timeout=8000)
    refused = page.request.delete(f'/api/conversations/sessions/{view.conversation_id}')
    assert refused.status == 409
    assert refused.json()['error'] == "This chat's goal is working. Pause the goal first, then try again."
    assert page.request.post(view.base + '/pause', data={}).ok
    view.wait(lambda g: g['claim'] is None)
    assert view.delete_chat().ok
    assert page.request.get(view.base).json()['goal'] is None


def test_archive_pauses_the_goal_and_restore_keeps_it_paused(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    assert view.current()['paused'] is False
    archived = page.request.post(f'/api/conversations/sessions/{view.conversation_id}/archive')
    assert archived.ok, archived.text()
    restored = page.request.post(f'/api/conversations/sessions/{view.conversation_id}/unarchive')
    assert restored.ok, restored.text()
    assert view.current()['paused'] is True
    page.reload()
    expect(view.header).to_contain_text('Paused')


def test_deleted_goal_chat_leaves_the_goals_page(goal_ui):
    view, page = goal_ui, goal_ui.page
    objective = 'Keep the community garden schedule current'
    view.assign(objective)
    page.get_by_test_id('sidebar-nav-goals').click()
    rows = page.get_by_test_id('goal-row')
    expect(rows.filter(has_text=objective)).to_have_count(1)
    assert page.request.post(view.base + '/pause', data={}).ok
    assert view.delete_chat().ok
    page.reload()
    expect(page.get_by_test_id('goals-view')).to_be_visible()
    expect(rows.filter(has_text=objective)).to_have_count(0)
