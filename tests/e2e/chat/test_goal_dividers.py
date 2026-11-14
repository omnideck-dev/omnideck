"""Where goal dividers sit in the chat: the first run, run outcomes, and centered labels."""

import pytest
from playwright.sync_api import Locator, Page, expect

from tests.e2e._protocol import say, slow
from tests.e2e.pages.goals_view import choose, future, goal_conversation, read_goal, update_questions, work_on


@pytest.fixture
def goal_ui(page: Page):
    with goal_conversation(page) as view:
        yield view


def follows(first: Locator, second: Locator) -> bool:
    """Whether *second* comes after *first* in the page."""
    return first.evaluate(
        '(node, other) => Boolean(node.compareDocumentPosition(other) & Node.DOCUMENT_POSITION_FOLLOWING)',
        second.element_handle(),
    )


def test_first_run_of_a_new_goal_has_no_divider_of_its_own(goal_ui):
    view = goal_ui
    view.assign()
    view.chat()
    assert view.transitions() == ['started', 'run', 'waiting']
    expect(view.dividers()).to_have_count(2)
    assert view.shown() == ['started', 'waiting']
    view.page.reload()
    expect(view.dividers()).to_have_count(2)
    assert view.shown() == ['started', 'waiting']


def test_outcome_shows_below_the_reply_once_the_run_finishes(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    view.chat()
    reply = 'Everything on the calendar is current. ' * 60
    view.composer.fill(read_goal() + choose('complete', 'Calendar is current.', outcome='Calendar is current.')
                       + slow() + say(reply))
    page.get_by_role('button', name='Send message', exact=True).click()
    stop = page.get_by_test_id('chat-stop-btn')
    expect(stop).to_be_visible()
    # The agent chose "complete" before writing its reply. While the reply streams, no outcome shows.
    view.wait(lambda g: g['next']['kind'] == 'done')
    assert view.transitions()[-1] == 'completed'
    expect(view.dividers('completed')).to_have_count(0)
    expect(stop).to_be_visible()
    expect(stop).to_have_count(0, timeout=20000)
    done = view.dividers('completed')
    expect(done).to_have_count(1)
    assert follows(page.get_by_test_id('message-assistant').last, done)
    assert view.shown() == ['started', 'waiting', 'completed']
    page.reload()
    expect(done).to_have_count(1)
    assert follows(page.get_by_test_id('message-assistant').last, done)


def test_run_that_changes_its_mind_shows_only_its_last_outcome(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    view.send(read_goal() + update_questions({'id': 'day', 'question': 'Which day works for you?'})
              + choose('wait_for_input', 'I need the day first.', question_ids=['day'])
              + work_on('Check the calendar again.')
              + choose('schedule', 'Checking again tomorrow instead.', at=future(24 * 60)),
              'I will check again tomorrow.')
    view.chat()
    assert view.transitions()[-2:] == ['waiting', 'scheduled']
    expect(view.dividers()).to_have_count(3)
    assert view.shown() == ['started', 'waiting', 'scheduled']
    reply = page.get_by_test_id('message-assistant').filter(has_text='I will check again tomorrow.')
    assert follows(reply, view.dividers('scheduled'))
    page.reload()
    expect(view.dividers()).to_have_count(3)
    assert view.shown() == ['started', 'waiting', 'scheduled']


def test_divider_labels_are_centered_while_the_time_is_hidden(goal_ui):
    view = goal_ui
    view.assign()
    view.chat()
    view.page.mouse.move(0, 0)
    for transition in ['started', 'waiting']:
        divider = view.dividers(transition)
        expect(divider.locator('time')).to_have_css('opacity', '0')
        # The visible part runs from the icon to the text just before the hidden time.
        offset = divider.evaluate('''(row) => {
            const time = row.querySelector('time');
            const start = row.querySelector('i').getBoundingClientRect().left;
            const end = time.previousElementSibling.getBoundingClientRect().right;
            const box = row.getBoundingClientRect();
            return (start + end) / 2 - (box.left + box.width / 2);
        }''')
        assert abs(offset) <= 1, f'{transition} divider is {offset}px off center'


def test_outcome_shows_after_reload_when_a_restart_cut_off_the_finish(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    view.send(read_goal() + choose('complete', 'Calendar is current.', outcome='Calendar is current.'),
              'The calendar is current.')
    expect(view.dividers('completed')).to_have_count(1)

    # A restart during a run leaves its turn without a saved finish. Reload the
    # chat as if the last turn's finish was never written and no run is active.
    def without_last_finish(route):
        response = route.fetch()
        snapshot = response.json()
        events = snapshot['events']
        last_root = [e['agent_id'] for e in events if e['type'] == 'agent_started' and not e.get('depth')][-1]
        snapshot['events'] = [e for e in events if not (e['type'] == 'agent_completed' and e['agent_id'] == last_root)]
        assert snapshot.get('active_run') is None
        route.fulfill(response=response, json=snapshot)

    page.route(f'**/api/conversations/sessions/{view.conversation_id}/resume', without_last_finish)
    page.reload()
    done = view.dividers('completed')
    expect(done).to_have_count(1)
    assert follows(page.get_by_test_id('message-assistant').filter(has_text='The calendar is current.'), done)
