"""Where goal dividers sit in the chat: the first run, run outcomes, and centered labels."""

from pathlib import Path

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


def test_first_run_of_a_new_goal_has_a_run_divider(goal_ui):
    view = goal_ui
    view.assign()
    view.chat()
    assert view.transitions() == ['run', 'waiting']
    expect(view.dividers()).to_have_count(2)
    assert view.shown() == ['run', 'waiting']
    view.page.reload()
    expect(view.dividers()).to_have_count(2)
    assert view.shown() == ['run', 'waiting']


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
    view.wait(lambda g: g['next']['kind'] == 'done')
    expect(view.dividers('completed')).to_have_count(0)
    expect(stop).to_be_visible()
    expect(stop).to_have_count(0, timeout=20000)
    done = view.dividers('completed')
    expect(done).to_have_count(1)
    assert view.transitions()[-1] == 'completed'
    assert follows(page.get_by_test_id('message-assistant').last, done)
    assert view.shown() == ['run', 'waiting', 'completed']
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
    assert view.transitions() == ['run', 'waiting', 'scheduled']
    expect(view.dividers()).to_have_count(3)
    assert view.shown() == ['run', 'waiting', 'scheduled']
    reply = page.get_by_test_id('message-assistant').filter(has_text='I will check again tomorrow.')
    assert follows(reply, view.dividers('scheduled'))
    page.reload()
    expect(view.dividers()).to_have_count(3)
    assert view.shown() == ['run', 'waiting', 'scheduled']


def test_run_that_does_not_change_what_is_next_shows_no_outcome(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    before = view.transitions()
    view.send(read_goal() + say('Nothing new to plan yet.'), 'Nothing new to plan yet.')
    assert view.current()['next'] == {'kind': 'wait', 'question_ids': []}
    assert view.transitions() == before
    view.chat()
    expect(view.dividers()).to_have_count(len(before))


def test_user_goal_actions_add_no_chat_event(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    view.send(read_goal() + choose('complete', 'Calendar is current.', outcome='Calendar is current.'),
              'The calendar is current.')
    view.wait(lambda g: g['next']['kind'] == 'done')
    before = view.events()
    reopened = page.request.post(view.base + '/reopen', data={'text': say('Back on it.'), 'profile_id': view.profile_id})
    assert reopened.ok, reopened.text()
    view.idle()
    after_reopen = view.events()
    for action in ('pause', 'resume', 'cancel'):
        response = page.request.post(f'{view.base}/{action}', data={})
        assert response.ok, response.text()
    assert view.events() == after_reopen
    added = after_reopen[len(before):]
    assert not any(e['type'] == 'goal' and e['data']['kind'] not in {'wakeup', 'waiting', 'scheduled', 'completed', 'error'}
                   for e in added)
    assert any(e['type'] == 'user_message' and 'Back on it.' in e['content'] for e in added)
    view.chat()
    page.reload()
    expect(view.dividers()).to_have_count(len([e for e in view.events() if e['type'] == 'goal' and e['data']['kind'] != 'edited']))


def test_dividers_fit_a_narrow_chat_and_show_the_time_on_hover(goal_ui, output_path: str):
    view, page = goal_ui, goal_ui.page
    view.assign('Keep our community calendar current, including school dates, library events, and neighborhood meetings')
    view.send(read_goal() + choose('complete', 'Calendar is current.', outcome='Calendar is current.'),
              'The calendar is current.')
    view.chat()
    expect(view.dividers()).to_have_count(3)
    assert view.shown() == ['run', 'waiting', 'completed']
    page.mouse.move(0, 0)
    for transition in ['run', 'waiting', 'completed']:
        divider = view.dividers(transition)
        expect(divider.locator('time')).to_have_css('opacity', '0')
        offset = divider.evaluate('''(row) => {
            const time = row.querySelector('time');
            const start = row.querySelector('i').getBoundingClientRect().left;
            const end = time.previousElementSibling.getBoundingClientRect().right;
            const box = row.getBoundingClientRect();
            return (start + end) / 2 - (box.left + box.width / 2);
        }''')
        assert abs(offset) <= 1, f'{transition} divider is {offset}px off center'
    run = view.dividers('run')
    run.hover()
    expect(run.locator('time')).to_have_css('opacity', '1')
    page.mouse.move(0, 0)
    before = view.dividers().all_text_contents()
    page.reload()
    expect(view.dividers()).to_have_count(3)
    assert view.dividers().all_text_contents() == before
    page.set_viewport_size({'width': 390, 'height': 844})
    collapse = page.get_by_role('button', name='Collapse sidebar', exact=True)
    if collapse.is_visible():
        collapse.click()
    for transition in ['run', 'waiting', 'completed']:
        divider = view.dividers(transition)
        divider.scroll_into_view_if_needed()
        box = divider.bounding_box()
        assert box['x'] >= 0 and box['x'] + box['width'] <= 390
        assert divider.evaluate('(node) => node.scrollWidth <= node.clientWidth')
    page.screenshot(path=str(Path(output_path) / 'goal-dividers-mobile.png'))
