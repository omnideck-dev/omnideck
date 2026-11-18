"""The Goals page and the sidebar's count of goals that need the user."""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.pages.goals_view import goal_conversation


@pytest.fixture
def goal_ui(page: Page):
    with goal_conversation(page) as view:
        yield view


def test_start_a_goal_from_the_goals_page(goal_ui):
    view, page = goal_ui, goal_ui.page
    objective = 'Plan the school bake sale'
    page.get_by_test_id('sidebar-nav-goals').click()
    expect(page.get_by_test_id('goals-view')).to_be_visible()
    page.get_by_role('button', name='Start a goal…', exact=True).first.click()
    dialog = page.get_by_role('dialog', name='Start a goal', exact=True)
    dialog.get_by_label('What would you like done?').fill(objective)
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/goal')) as created:
        dialog.get_by_role('button', name='Start goal', exact=True).click()
    assert created.value.status == 201, created.value.text()
    goal = created.value.json()['goal']
    expect(dialog).to_have_count(0)
    expect(page.get_by_test_id('view-tab-goal')).to_have_count(0)
    expect(page.get_by_test_id('chat-title')).to_have_text(objective)
    expect(page.get_by_test_id('goal-headline')).to_be_visible(timeout=10000)
    other = view.__class__(page, goal['conversation_id'], view.profile_id)
    try:
        other.idle()
        page.get_by_test_id('sidebar-nav-goals').click()
        expect(page.get_by_test_id('goal-row').filter(has_text=objective)).to_have_count(1)
    finally:
        page.request.post(other.base + '/pause', data={})
        other.delete_chat()


def test_waiting_goal_raises_the_sidebar_count_until_answers_are_sent(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    goals_row = page.get_by_test_id('sidebar-nav-goals')
    expect(goals_row).to_have_accessible_name('Goals')
    view.ask()
    expect(goals_row).to_have_accessible_name('Goals, 1 needs you')
    expect(goals_row.get_by_test_id('sidebar-goals-needs-you')).to_have_text('1')
    page.get_by_role('button', name='Saturday', exact=True).click()
    view.composer.fill('The library')
    page.get_by_role('button', name='Send 2 answers', exact=True).click()
    view.idle()
    expect(goals_row).to_have_accessible_name('Goals')
    expect(goals_row.get_by_test_id('sidebar-goals-needs-you')).to_have_count(0)
