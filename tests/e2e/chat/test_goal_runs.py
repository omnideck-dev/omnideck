"""Goal runs, errors, stop, pause, run now and reopen through real runs of the fake model."""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._protocol import provider_fail, say, slow
from tests.e2e._runtime import delete_conversation, run_turn, update_conversation
from tests.e2e.pages.goals_view import (
    choose, future, goal_conversation, read_goal, update_goal, update_questions, work_on,
)


@pytest.fixture
def goal_ui(page: Page):
    with goal_conversation(page) as view:
        yield view


def test_unrelated_message_keeps_goal_waiting(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    view.send(read_goal() + update_questions({'id': 'day', 'question': 'Which day works for you?'})
              + choose('wait_for_input', 'I need the day first.', question_ids=['day']), 'Which day works for you?')
    expect(view.header).to_contain_text('1 question for you')
    waiting = view.current()
    view.send('', 'It is 3 PM.')
    page.reload()
    expect(view.header).to_contain_text('1 question for you')
    saved = view.current()
    assert saved['next'] == {'kind': 'wait', 'question_ids': ['day']}
    assert saved['revision'] == waiting['revision']
    assert saved['last_run_id'] != waiting['last_run_id']
    # Needs you cannot be collapsed, and the Goals filter keeps only chats with a goal.
    sidebar = page.get_by_test_id('sidebar')
    needs_you = sidebar.locator('[data-section="needs-you"]')
    expect(needs_you.get_by_test_id('recent-item')).to_have_count(1)
    expect(needs_you.get_by_test_id('recent-section-label')).to_contain_text('Needs you')
    expect(needs_you.get_by_role('button', name='Needs you')).to_have_count(0)
    other = 'e2e-goal-filter-' + view.conversation_id
    run_turn(other, say('Nothing to plan here.'))
    update_conversation(other, title='A chat without a goal')
    try:
        page.reload()
        items = sidebar.get_by_test_id('recent-item')
        expect(items.filter(has_text='A chat without a goal')).to_have_count(1)
        sidebar.get_by_test_id('recent-filter').click()
        page.get_by_role('menuitemradio', name='With a goal').click()
        expect(items.filter(has_text='A chat without a goal')).to_have_count(0)
        expect(items).to_have_count(sidebar.get_by_test_id('goal-status').count())
        sidebar.get_by_role('button', name='Clear Goals filter').click()
    finally:
        delete_conversation(other)


def test_failed_goal_run_shows_error(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    view.send(read_goal() + work_on(provider_fail('Rate limit reached (429).'), 'call')
              + choose('continue', 'Calling the parks office next.'), 'Starting the call.')
    failed = view.wait(lambda g: g['next']['kind'] == 'error')
    assert 'Rate limit reached (429).' in failed['next']['message']
    expect(view.header).to_contain_text('Stopped by an error')
    expect(view.dividers('error')).to_have_count(1)
    expect(view.dividers('error')).to_contain_text('Stopped by an error')
    assert view.transitions() == ['started', 'run', 'waiting', 'run', 'error']
    expect(page.locator('[data-section="needs-you"]')).to_contain_text('Stopped by an error')
    view.open()
    error = view.details.get_by_test_id('goal-error')
    expect(error).to_contain_text('Rate limit reached (429).')
    expect(view.details.get_by_role('button', name='Run now', exact=True)).to_have_count(0)
    # The user rewrites the step so the retried run can succeed; Retry runs the step in progress again.
    view.details.get_by_role('button', name='Edit', exact=True).click()
    dialog = page.get_by_role('dialog', name='Edit', exact=True)
    dialog.locator('summary').filter(has_text='Plan').first.click()
    dialog.locator('section[aria-label="Edit plan"] summary').first.click()
    dialog.get_by_label('Step 1 title').fill(say('Booked the pavilion after the retry.'))
    dialog.get_by_role('button', name='Save changes', exact=True).click()
    expect(dialog).to_have_count(0)
    error.get_by_role('button', name='Retry', exact=True).click()
    expect(page.get_by_test_id('message-assistant').filter(has_text='Booked the pavilion after the retry.')).to_be_visible(timeout=15000)
    retried = view.idle()
    assert retried['last_run_id'] != failed['last_run_id']
    assert retried['next'] == {'kind': 'wait', 'question_ids': []}
    expect(view.details.get_by_test_id('goal-error')).to_have_count(0)
    expect(view.dividers('error')).to_have_count(1)
    expect(view.dividers('run')).to_have_count(2)
    assert view.transitions() == ['started', 'run', 'waiting', 'run', 'error', 'run', 'waiting']


def test_stop_keeps_goal_schedule(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    scheduled = view.schedule('Check the library calendar for new dates.')
    expect(view.header).to_contain_text('Resumes')
    view.composer.fill(slow() + say('I am checking venue availability. ' * 150))
    page.get_by_role('button', name='Send message', exact=True).click()
    stop = page.get_by_test_id('chat-stop-btn')
    expect(stop).to_be_visible()
    expect(view.composer).to_have_attribute('placeholder', 'Message the agent while it works…', timeout=8000)
    assert stop.get_attribute('title').startswith('Stops this run. The goal will still run ')
    stop.click()
    expect(stop).to_have_count(0, timeout=10000)
    stopped = view.idle()
    assert stopped['paused'] is False
    assert stopped['next'] == scheduled['next']
    expect(view.header).to_contain_text('Resumes')
    expect(view.header).not_to_contain_text('Paused')
    expect(view.dividers('paused')).to_have_count(0)


def test_answer_still_sends_when_agent_lists_the_same_question_again(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    question = {'id': 'day', 'question': 'Which day works for you?', 'choices': ['Saturday', 'Sunday']}
    view.send(read_goal() + update_questions(question)
              + choose('wait_for_input', 'I need the day first.', question_ids=['day']), 'Which day works?')
    expect(view.questions).to_be_visible()
    asked = view.current()['questions'][0]
    view.composer.fill('Saturday morning')
    # A run the user did not start lists the same question again, unchanged.
    view.background(read_goal() + update_questions(question) + say('Still checking the venues.'))
    expect(page.get_by_test_id('message-assistant').filter(has_text='Still checking the venues.')).to_be_visible(timeout=10000)
    relisted = view.current()['questions'][0]
    assert relisted['revision'] == asked['revision']
    expect(view.questions).to_be_visible()
    expect(view.composer).to_have_value('Saturday morning')
    expect(page.get_by_text('The question changed.', exact=False)).to_have_count(0)
    page.get_by_role('button', name='Send answer', exact=True).click()
    expect(page.get_by_test_id('message-user').last).to_contain_text('Which day works for you?')
    expect(page.get_by_test_id('message-user').last).to_contain_text('Saturday morning')
    expect(page.get_by_text('A question changed', exact=False)).to_have_count(0)
    view.idle()
    saved = view.current()['questions'][0]
    assert [answer['answer'] for answer in saved['answers']] == ['Saturday morning']


def test_pause_and_resume_keep_future_schedule(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    scheduled = view.schedule('Check the library calendar for new dates.', at=future(2 * 24 * 60))
    view.open()
    expect(view.details.get_by_role('button', name='Run now', exact=True)).to_be_visible()
    view.details.get_by_role('button', name='Pause', exact=True).click()
    paused = view.wait(lambda g: g['paused'])
    assert paused['next'] == scheduled['next']
    expect(view.header).to_contain_text('Paused')
    expect(view.details.get_by_test_id('goal-reason')).to_contain_text('as planned')
    expect(view.details.get_by_role('button', name='Run now', exact=True)).to_have_count(0)
    view.details.get_by_role('button', name='Resume', exact=True).click()
    resumed = view.wait(lambda g: not g['paused'])
    assert resumed['next'] == scheduled['next']
    expect(view.header).to_contain_text('Resumes')
    expect(view.details.get_by_role('button', name='Run now', exact=True)).to_be_visible()
    # Resume never starts a run.
    page.wait_for_timeout(1500)
    assert view.current()['last_run_id'] == scheduled['last_run_id']
    expect(view.dividers('paused')).to_have_count(1)
    expect(view.dividers('resumed')).to_have_count(1)
    assert view.transitions()[-2:] == ['paused', 'resumed']


def test_run_now_runs_the_scheduled_step_now(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    scheduled = view.schedule(say('Checked the library calendar early.'))
    view.open()
    expect(view.details.get_by_role('region', name='Next up')).to_contain_text('Checked the library calendar early.')
    expect(view.details.get_by_test_id('goal-error')).to_have_count(0)
    view.details.get_by_role('button', name='Run now', exact=True).click()
    expect(page.get_by_test_id('message-assistant').filter(has_text='Checked the library calendar early.')).to_be_visible(timeout=15000)
    ran = view.idle()
    assert ran['last_run_id'] != scheduled['last_run_id']
    assert ran['next'] == {'kind': 'wait', 'question_ids': []}
    run = view.dividers('run')
    expect(run).to_have_count(1)
    expect(run.last).to_contain_text('Goal run')
    expect(run.last).to_contain_text('Checked the library calendar early.')
    wakeups = [e for e in view.events() if e['type'] == 'goal' and e['data']['kind'] == 'wakeup']
    assert wakeups[-1]['data']['reason'] == 'run_now'
    assert wakeups[-1]['data']['wake_id'] == scheduled['next']['id']
    expect(view.details.get_by_role('button', name='Run now', exact=True)).to_have_count(0)
    expect(view.details.get_by_role('region', name='Next up')).to_have_count(0)


def test_reopen_done_goal_sends_text_and_runs_again(goal_ui):
    view, page = goal_ui, goal_ui.page
    first = view.assign('Arrange a community picnic')
    view.send(read_goal() + work_on('Book the pavilion', 'pavilion')
              + choose('complete', 'Booked the pavilion.', outcome='Riverside Park pavilion booked for Saturday.'),
              'The picnic is arranged.')
    done = view.wait(lambda g: g['next']['kind'] == 'done')
    expect(view.header).to_contain_text('Done')
    view.open()
    expect(view.details.get_by_test_id('goal-outcome')).to_contain_text('Riverside Park pavilion booked for Saturday.')
    expect(view.details.get_by_role('button', name='Edit', exact=True)).to_have_count(0)
    expect(view.details.get_by_role('button', name='Start a new goal…', exact=True)).to_be_visible()
    view.details.get_by_role('button', name='More goal actions', exact=True).click()
    expect(page.get_by_role('menuitem', name='Open goal history', exact=True)).to_be_visible()
    expect(page.get_by_role('menuitem', name='Cancel goal', exact=True)).to_have_count(0)
    page.keyboard.press('Escape')
    view.details.get_by_role('button', name='Reopen…', exact=True).click()
    dialog = page.get_by_role('dialog', name='Reopen goal', exact=True)
    expect(dialog.get_by_role('button', name='Reopen and run', exact=True)).to_be_disabled()
    request = 'Also book a band for the picnic.'
    dialog.get_by_role('textbox').fill(
        request + read_goal() + update_goal(plan=[
            {'id': 'pavilion', 'status': 'done'},
            {'id': 'band', 'title': say('The band is booked.'), 'status': 'in_progress'},
        ])
        + choose('continue', 'Added a step to book the band.') + say('I will book the band now.'))
    dialog.get_by_role('button', name='Reopen and run', exact=True).click()
    expect(dialog).to_have_count(0)
    view.chat()
    expect(page.get_by_test_id('message-user').filter(has_text=request)).to_have_count(1, timeout=10000)
    expect(view.dividers('reopened')).to_have_count(1)
    expect(view.dividers('reopened')).to_contain_text('Goal reopened')
    expect(page.get_by_test_id('message-assistant').filter(has_text='I will book the band now.')).to_be_visible(timeout=15000)
    expect(page.get_by_test_id('message-assistant').filter(has_text='The band is booked.')).to_be_visible(timeout=15000)
    reopened = view.idle()
    assert reopened['id'] == first['id']
    assert reopened['next'] == {'kind': 'wait', 'question_ids': []}
    assert [step['id'] for step in reopened['plan']] == ['pavilion', 'band']
    assert reopened['history_count'] > done['history_count']
    assert view.transitions()[-4:] == ['completed', 'reopened', 'run', 'waiting']
    expect(view.header).to_contain_text('Waiting for you')
