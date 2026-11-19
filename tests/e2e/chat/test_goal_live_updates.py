"""Goal and run changes reach an open chat without a reload."""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._protocol import say
from tests.e2e.pages.goals_view import choose, future, goal_conversation, read_goal, work_on


@pytest.fixture
def goal_ui(page: Page):
    with goal_conversation(page) as view:
        yield view


def test_scheduler_wake_run_appears_in_the_open_chat(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    answer = 'Checked the calendar on schedule.'
    view.send(read_goal() + work_on(say(answer)) + choose('schedule', 'Checking in a moment.', at=future(3 / 60)),
              'I will check in a moment.')
    expect(page.get_by_test_id('message-assistant').filter(has_text=answer)).to_be_visible(timeout=20000)
    expect(view.dividers('run')).to_have_count(2)
    expect(view.header).to_contain_text('Waiting for you', timeout=10000)


def test_pause_in_a_second_tab_shows_in_the_first_tab(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    expect(view.header).to_contain_text('Waiting for you')
    other = page.context.new_page()
    try:
        other.goto('/')
        assert other.request.post(view.base + '/pause', data={}).ok
    finally:
        other.close()
    expect(view.header).to_contain_text('Paused', timeout=10000)
    expect(page.get_by_test_id('sidebar').get_by_test_id('goal-status')).to_contain_text('Paused')


def test_message_sent_in_a_second_tab_shows_in_the_first_tab(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    other = page.context.new_page()
    try:
        other.goto('/')
        response = other.request.post('/api/chat', data={
            'conversation_id': view.conversation_id, 'profile_id': view.profile_id,
            'message': 'Hello from the other tab' + say('Hello back from the agent.'),
        })
        assert response.ok, response.text()
    finally:
        other.close()
    expect(page.get_by_test_id('message-user').filter(has_text='Hello from the other tab')).to_be_visible(timeout=10000)
    expect(page.get_by_test_id('message-assistant').filter(has_text='Hello back from the agent.')).to_be_visible(timeout=10000)
