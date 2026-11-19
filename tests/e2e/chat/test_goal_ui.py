"""Goal entry, controls, recovery, and lifecycle through the real browser and fake model."""

from datetime import datetime, timedelta, timezone

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._protocol import bash, say, slow
from tests.e2e.pages import SettingsPage
from tests.e2e.pages.goals_view import (
    choose, goal_conversation, read_goal, update_goal, update_questions, work_on,
)


@pytest.fixture
def goal_ui(page: Page):
    with goal_conversation(page) as view:
        yield view


@pytest.mark.parametrize('entry', ['plus', 'slash'])
def test_create_goal_from_composer_entry_and_cancel_unsaved_dialog(goal_ui, entry):
    view, page = goal_ui, goal_ui.page
    objective = 'Arrange the neighborhood picnic'
    if entry == 'slash':
        view.composer.fill('/')
        expect(page.get_by_test_id('slash-hint')).to_contain_text('Start a goal for this chat')
    dialog = view.open_assignment(entry, objective)
    expect(dialog).to_contain_text('come back later')
    dialog.get_by_label('What would you like done?').fill(objective)
    dialog.get_by_role('button', name='Cancel', exact=True).click()
    assert view.current() is None
    view.assign(objective, entry)
    expect(view.header).to_contain_text('Waiting for you')
    expect(page.get_by_test_id('view-tab-goal')).to_have_count(0)
    assert view.transitions() == ['run', 'waiting']
    assert not any(e['type'] == 'user_message' and e['content'].startswith('/goal') for e in view.events())
    expect(view.dividers('run')).to_have_count(1)
    expect(view.dividers('started')).to_have_count(0)
    page.get_by_role('button', name='Add to chat', exact=True).click()
    expect(page.get_by_role('menuitem', name='Open goal /goal', exact=True)).to_be_visible()
    page.keyboard.press('Escape')
    view.composer.fill('/')
    expect(page.get_by_test_id('slash-hint')).to_contain_text("Open this chat's goal")
    view.composer.fill('')
    page.reload()
    view.open()
    expect(view.details).to_contain_text(objective)
    expect(page.get_by_test_id('view-tab-goal')).to_contain_text('Goal · ')


def test_goals_off_and_on_leaves_goals_unchanged(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    scheduled = view.send(read_goal() + work_on('Check the library calendar')
                          + update_goal(summary='Library dates checked')
                          + choose('schedule', 'Checked the library dates.', at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat()),
                          'I will check again tomorrow.')
    SettingsPage(page).goto_system()
    toggle = page.get_by_role('switch', name='Goals', exact=True)
    expect(toggle).to_be_checked()
    expect(page.get_by_test_id('goals-toggle')).to_contain_text('Goals pick up where they left off')
    with page.expect_response(
        lambda response: response.url.endswith('/api/settings') and response.request.method == 'PUT'
    ) as disabled_response:
        page.get_by_test_id('goals-toggle').click()
    assert disabled_response.value.ok
    expect(page.get_by_test_id('goals-toggle')).to_have_count(0)
    assert page.request.get('/api/settings').json()['goals_enabled'] is False
    view.chat()
    page.get_by_role('button', name='Add to chat', exact=True).click()
    expect(page.get_by_role('menuitem', name='Attach file', exact=True)).to_be_visible()
    expect(page.get_by_role('menuitem', name='Start a goal… /goal', exact=True)).to_have_count(0)
    expect(page.get_by_role('menuitem', name='Open goal /goal', exact=True)).to_have_count(0)
    page.keyboard.press('Escape')
    expect(view.header).to_have_count(0)
    SettingsPage(page).goto_system()
    page.evaluate("localStorage.removeItem('omnideck_early_access')")
    page.reload()
    SettingsPage(page).goto_system()
    expect(page.get_by_test_id('goals-toggle')).to_have_count(0)
    SettingsPage(page).unlock_early_access()
    expect(page.get_by_test_id('goals-toggle')).to_be_visible()
    with page.expect_response(
        lambda response: response.url.endswith('/api/settings') and response.request.method == 'PUT'
    ) as enabled_response:
        page.get_by_test_id('goals-toggle').click()
    assert enabled_response.value.ok
    expect(toggle).to_be_checked()
    view.chat()
    saved = view.current()
    for field in ('id', 'revision', 'next', 'paused', 'summary', 'plan', 'note'):
        assert saved[field] == scheduled[field], field
    expect(view.header).to_contain_text('Resumes')
    view.open()
    expect(view.details.get_by_role('button', name='Pause', exact=True)).to_be_visible()


def test_goal_controls_pause_resume_and_confirm_cancel(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    view.open()
    view.details.get_by_role('button', name='Pause', exact=True).click()
    view.wait(lambda g: g['paused'])
    expect(view.details.get_by_test_id('goal-reason')).to_contain_text('keeps waiting for you')
    view.details.get_by_role('button', name='Resume', exact=True).click()
    view.wait(lambda g: not g['paused'])
    view.send(read_goal() + work_on(say('Manual return processed.')) + choose('continue', 'Processing the return next.'),
              'Processing the return.')
    expect(page.get_by_test_id('message-assistant').filter(has_text='Manual return processed.')).to_be_visible(timeout=15000)
    view.idle()
    view.open()
    view.more_actions('Cancel goal')
    assert view.current()['next']['kind'] != 'cancelled'
    page.get_by_role('menuitem', name='Cancel this goal?', exact=True).click()
    view.wait(lambda g: g['next']['kind'] == 'cancelled')
    expect(view.details.get_by_role('button', name='Reopen…', exact=True)).to_be_visible()
    expect(view.details.get_by_role('button', name='Start a new goal…', exact=True)).to_be_visible()
    expect(view.header).to_contain_text('Cancelled')
    expected = ['run', 'waiting', 'run', 'waiting']
    assert view.transitions() == expected
    view.chat()
    expect(view.dividers()).to_have_count(len(expected))
    assert view.shown() == expected
    page.reload()
    expect(view.dividers()).to_have_count(len(expected))
    assert view.shown() == expected
    expect(view.header).to_contain_text('Cancelled')


def test_goal_editor_saves_plan_and_recovers_real_revision_conflict(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    view.send(read_goal() + work_on('Confirm the park booking', 'park'), 'Planned the booking.')
    view.open()
    view.details.get_by_role('button', name='Edit', exact=True).click()
    dialog = page.get_by_role('dialog', name='Edit', exact=True)
    dialog.get_by_label('What would you like done?').fill('Coordinate the spring picnic')
    dialog.locator('summary').filter(has_text='Plan').first.click()
    expect(dialog.get_by_role('combobox')).to_have_count(0)
    dialog.get_by_role('button', name='Add step', exact=True).click()
    dialog.get_by_label('Step 2 title').fill('Send the invitations')
    dialog.get_by_label('Step 2 notes').fill('Include the covered shelter location.')
    dialog.get_by_role('button', name='Save changes', exact=True).click()
    expect(dialog).to_have_count(0)
    saved = view.current()
    assert saved['objective'] == 'Coordinate the spring picnic'
    assert [(step['title'], step['status']) for step in saved['plan']] == [
        ('Confirm the park booking', 'in_progress'), ('Send the invitations', 'pending')]
    assert saved['plan'][1]['notes'] == 'Include the covered shelter location.'
    step_ids = [step['id'] for step in saved['plan']]
    page.reload()
    expect(view.details).to_contain_text('Coordinate the spring picnic')
    view.details.get_by_role('button', name='Edit', exact=True).click()
    dialog.get_by_label('What would you like done?').fill('My unsaved picnic changes')
    view.background(read_goal() + update_goal(plan=[{'id': step_ids[0], 'status': 'done'}, {'id': step_ids[1]}])
                    + say('The park is booked.'))
    assert view.current()['revision'] > saved['revision']
    dialog.get_by_role('button', name='Save changes', exact=True).click()
    expect(dialog).to_contain_text('Your changes are still here')
    expect(dialog.get_by_label('What would you like done?')).to_have_value('My unsaved picnic changes')
    expect(dialog.get_by_role('button', name='Save changes', exact=True)).to_be_disabled()
    dialog.get_by_role('button', name='Load latest version', exact=True).click()
    expect(dialog.get_by_label('What would you like done?')).to_have_value('Coordinate the spring picnic')
    dialog.get_by_label('What would you like done?').fill('Finalize the June picnic')
    dialog.get_by_role('button', name='Save changes', exact=True).click()
    expect(dialog).to_have_count(0)
    final = view.current()
    assert [step['id'] for step in final['plan']] == step_ids
    assert final['plan'][0]['status'] == 'done'
    assert final['objective'] == 'Finalize the June picnic'


def test_goal_dialog_retries_failed_creation_without_losing_input(goal_ui):
    view, page = goal_ui, goal_ui.page
    failures = {'POST': 1}

    def fail_once(route):
        if failures.get(route.request.method, 0):
            failures[route.request.method] -= 1
            route.fulfill(status=503, json={'error': 'Temporary goal service failure'})
        else:
            route.continue_()

    page.route('**' + view.base, fail_once)
    page.get_by_role('button', name='Add to chat', exact=True).click()
    page.get_by_role('menuitem', name='Start a goal… /goal', exact=True).click()
    dialog = page.get_by_role('dialog', name='Start a goal', exact=True)
    dialog.get_by_label('What would you like done?').fill('Plan a neighborhood cleanup')
    dialog.get_by_role('button', name='Start goal', exact=True).click()
    expect(dialog).to_contain_text('Temporary goal service failure')
    expect(dialog.get_by_label('What would you like done?')).to_have_value('Plan a neighborhood cleanup')
    assert view.current() is None
    dialog.get_by_role('button', name='Start goal', exact=True).click()
    expect(dialog).to_have_count(0)
    view.idle()
    assert view.transitions().count('run') == 1


def test_goal_control_failure_can_be_retried_without_duplicate_transition(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    view.open()
    page.route('**' + view.base + '/pause', lambda route: route.fulfill(status=503, json={'error': 'Pause temporarily unavailable'}), times=1)
    view.details.get_by_role('button', name='Pause', exact=True).click()
    expect(view.details).to_contain_text('Pause temporarily unavailable')
    assert view.current()['paused'] is False
    view.details.get_by_role('button', name='Pause', exact=True).click()
    view.wait(lambda g: g['paused'])
    expect(view.details).not_to_contain_text('Pause temporarily unavailable')
    history = page.request.get(view.base + '/history', params={'goal_id': view.current()['id']}).json()['entries']
    assert sum(entry['summary'] == 'Paused the goal.' for entry in history) == 1
    assert 'paused' not in view.transitions()


@pytest.mark.parametrize('paused', [False, True])
def test_partial_goal_answers_leave_blank_questions_open_and_respect_pause(goal_ui, paused):
    view, page = goal_ui, goal_ui.page
    view.assign()
    view.ask()
    expect(view.header).to_contain_text('2 questions for you')
    if paused:
        view.open()
        view.details.get_by_role('button', name='Pause', exact=True).click()
        view.wait(lambda g: g['paused'])
        view.chat()
        expect(view.questions).to_contain_text('The goal stays paused')
    page.get_by_role('button', name='Saturday', exact=True).click()
    expect(view.questions).to_contain_text('Where should we meet?')
    expect(view.composer).to_have_value('')
    page.get_by_role('button', name='Send answer', exact=True).click()
    expect(page.get_by_test_id('message-user').last).to_contain_text('Which day works for you?')
    expect(page.get_by_test_id('message-user').last).to_contain_text('Saturday')
    expect(view.questions).to_contain_text('Where should we meet?')
    view.idle()
    saved = view.current()
    assert saved['paused'] is paused
    assert saved['next'] == {'kind': 'wait', 'question_ids': ['day', 'place']}
    assert saved['questions'][0]['answers'][0]['answer'] == 'Saturday'
    assert saved['questions'][1]['answers'] == []
    answers = [e for e in view.events() if e['type'] == 'user_message' and e.get('context')]
    assert len(answers) == 1 and [q['question_id'] for q in answers[0]['context']] == ['day']


def test_changed_question_requires_draft_review_before_batch_submission(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    view.ask()
    view.composer.fill('Saturday')
    view.questions.get_by_role('button', name='Skip for now', exact=True).click()
    expect(view.questions).to_contain_text('Where should we meet?')
    view.composer.fill('The library')
    view.background(read_goal() + update_questions({
        'id': 'day', 'question': 'Which Sunday works for you?', 'choices': ['Next Sunday'],
    }) + say('The venue is only available on Sundays.'))
    expect(page.get_by_text('Another drafted answer needs review because its question changed.')).to_be_visible(timeout=10000)
    expect(page.get_by_role('button', name='Send answer', exact=True)).to_be_disabled()
    page.get_by_role('button', name='Review answer', exact=True).click()
    expect(view.composer).to_have_value('Saturday')
    expect(page.get_by_text('The question changed. Edit your draft or pick a choice to confirm your answer.')).to_be_visible()
    page.get_by_role('button', name='Next Sunday', exact=True).click()
    page.get_by_role('button', name='Send 2 answers', exact=True).click()
    expect(page.get_by_test_id('message-user').last).to_contain_text('Which Sunday works for you?')
    view.idle()
    saved = view.current()
    assert saved['questions'][0]['answers'][0]['answer'] == 'Next Sunday'
    assert saved['questions'][1]['answers'][0]['answer'] == 'The library'


def test_answers_during_active_goal_are_delivered_to_the_same_run(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    script = read_goal() + update_questions({
        'id': 'day', 'question': 'Which day works?', 'choices': ['Saturday'],
    }) + slow() + say('I am checking venue availability. ' * 150)
    view.composer.fill(script)
    page.get_by_role('button', name='Send message', exact=True).click()
    expect(view.questions).to_be_visible(timeout=10000)
    expect(page.get_by_test_id('chat-stop-btn')).to_be_visible()
    expect(page.get_by_role('button', name='Send answer', exact=True)).to_have_count(0)
    running = view.current()['last_run_id']
    page.get_by_role('button', name='Saturday', exact=True).click()
    expect(page.get_by_test_id('chat-stop-btn')).to_have_count(0)
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/goal/answers')) as sent:
        page.get_by_role('button', name='Send answer', exact=True).click()
    assert sent.value.status == 202, sent.value.text()
    expect(page.get_by_role('region', name="Queued for the agent's next step")).to_contain_text('Answers to 1 question')
    expect(view.questions).to_have_count(0)
    expect(page.get_by_role('button', name='Send answer', exact=True)).to_have_count(0)
    expect(page.get_by_test_id('chat-stop-btn')).to_be_visible()
    expect(page.locator("[role='region'][aria-label='Notifications']")).not_to_contain_text('sent')
    expect(page.get_by_test_id('goal-question-answer').filter(has_text='Saturday')).to_be_visible(timeout=40000)
    expect(page.get_by_role('region', name="Queued for the agent's next step")).to_have_count(0)
    view.wait(lambda g: g['claim'] is None, timeout=25)
    answers = [e for e in view.events() if e['type'] == 'user_message' and e.get('context')]
    assert len(answers) == 1 and answers[0]['is_nudge'] is True and answers[0]['nudge_id']
    assert view.current()['last_run_id'] == running
    assert view.current()['questions'][0]['answers'][0]['answer'] == 'Saturday'


def test_fake_provider_drives_goal_lifecycle_transcript_and_previous_goals(goal_ui):
    view, page = goal_ui, goal_ui.page
    first = view.assign('Arrange a community picnic')
    view.send(read_goal() + work_on('Confirm the picnic location', 'venue')
              + update_goal(summary='Choose a location before reserving it')
              + update_questions({'id': 'location', 'question': 'Which picnic location should I reserve?', 'choices': ['Riverside Park']})
              + choose('wait_for_input', 'I need the picnic location.', question_ids=['location']),
              'I need your preferred picnic location.')
    expect(view.header).to_contain_text('1 question for you')
    page.get_by_role('button', name='Riverside Park', exact=True).click()
    page.get_by_role('button', name='Send answer', exact=True).click()
    expect(page.get_by_test_id('message-user').last).to_contain_text('Which picnic location should I reserve?')
    view.idle()
    completion = (read_goal() + choose('complete', 'Confirmed the booking.', outcome='Riverside Park booking confirmed.')
                  + say('The picnic booking is confirmed.'))
    follow_up = (datetime.now(timezone.utc) + timedelta(seconds=6)).isoformat()
    view.composer.fill(read_goal() + update_questions({'id': 'location', 'status': 'resolved'})
                       + update_goal(summary='Reserve Riverside Park.', plan=[{'id': 'venue', 'title': completion}])
                       + choose('schedule', 'Reserved Riverside Park.', at=follow_up)
                       + say('I will return to verify the booking.'))
    page.get_by_role('button', name='Send message', exact=True).click()
    expect(page.get_by_test_id('message-assistant').filter(has_text='I will return to verify the booking.')).to_be_visible()
    expect(view.dividers('scheduled')).to_have_count(1)
    expect(view.dividers('scheduled')).to_contain_text('Resumes')
    view.wait(lambda g: g['next']['kind'] == 'done' and g['claim'] is None, timeout=20)
    expect(page.get_by_test_id('message-assistant').filter(has_text='The picnic booking is confirmed.')).to_be_visible(timeout=10000)
    expected = ['run', 'waiting', 'waiting', 'scheduled', 'run', 'completed']
    assert view.transitions() == expected
    dividers = view.dividers()
    labels = ['Goal run', 'Waiting for you', '1 question', 'Resumes', 'Goal run', 'Goal done']
    expect(dividers).to_have_count(len(labels))
    for index, label in enumerate(labels):
        expect(dividers.nth(index)).to_contain_text(label)
    events = view.events()
    assert len({e['id'] for e in events}) == len(events)
    visible = [e for e in events if e['type'] == 'goal']
    assert [e['timestamp'] for e in visible] == sorted(e['timestamp'] for e in visible)
    calls = [c['name'] for e in events if e['type'] == 'iteration' for c in e.get('tool_calls', [])]
    assert {'read_goal', 'update_goal', 'update_goal_questions', 'choose_next_action'} <= set(calls)
    expect(page.get_by_test_id('day-header')).to_have_count(1)
    texts = dividers.all_text_contents()
    page.reload()
    expect(dividers).to_have_count(len(texts))
    assert dividers.all_text_contents() == texts
    view.open()
    expect(view.details.get_by_test_id('goal-outcome')).to_contain_text('Riverside Park booking confirmed.')
    view.details.get_by_role('button', name='Start a new goal…', exact=True).click()
    dialog = page.get_by_role('dialog', name='Start a goal', exact=True)
    dialog.get_by_label('What would you like done?').fill('Arrange the next community event')
    dialog.get_by_role('button', name='Start goal', exact=True).click()
    expect(dialog).to_have_count(0)
    next_goal = view.wait(lambda g: g['id'] != first['id'] and g['last_run_id'] and g['claim'] is None and g['next']['kind'] == 'wait')
    view.details.locator('summary').filter(has_text='Previous goals').click()
    expect(view.details).to_contain_text(first['objective'])
    expect(view.details).to_contain_text('Riverside Park booking confirmed.')
    view.cancel()
    view.chat()
    expect(dividers).to_have_count(len(labels) + 2)
    assert next_goal['id'] != first['id']
    page.reload()
    expect(dividers).to_have_count(len(labels) + 2)


def test_edit_is_off_while_a_run_holds_the_goal_and_pause_turns_it_on(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    view.open()
    edit = view.details.get_by_role('button', name='Edit', exact=True)
    expect(edit).to_be_enabled()
    view.composer.fill(read_goal() + bash('sleep 8') + say('Checked every venue.'))
    page.get_by_role('button', name='Send message', exact=True).click()
    expect(edit).to_be_disabled(timeout=8000)
    expect(view.details).to_contain_text('The agent is working. Pause it to edit now.')
    refused = page.request.patch(view.base, data={'expected_revision': view.current()['revision'], 'objective': 'Too early'})
    assert refused.status == 409, refused.text()
    view.details.get_by_role('button', name='Pause', exact=True).click()
    view.wait(lambda g: g['paused'] and g['claim'] is None)
    expect(edit).to_be_enabled(timeout=10000)
    saved = page.request.patch(view.base, data={'expected_revision': view.current()['revision'], 'objective': 'Edited while paused'})
    assert saved.ok, saved.text()


def test_panel_edit_opens_the_next_run_with_an_edited_event(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    view.open()
    view.details.get_by_role('button', name='Edit', exact=True).click()
    dialog = page.get_by_role('dialog', name='Edit', exact=True)
    dialog.get_by_label('What would you like done?').fill('Keep the library calendar current')
    dialog.get_by_role('button', name='Save changes', exact=True).click()
    expect(dialog).to_have_count(0)
    assert 'edited' not in view.transitions()
    view.send('', 'Noted the change.')
    events = view.events()
    edited = [index for index, e in enumerate(events) if e['type'] == 'goal' and e['data']['kind'] == 'edited']
    assert len(edited) == 1
    reply = next(index for index, e in enumerate(events)
                 if e['type'] == 'iteration' and 'Noted the change.' in (e.get('content') or ''))
    assert edited[0] < reply
    assert 'The user edited the goal' in events[edited[0]]['model_text']
    view.chat()
    expect(view.dividers('edited')).to_have_count(0)
    users = page.get_by_test_id('message-user')
    expect(users.filter(has_text='[System notice')).to_have_count(0)


def test_goals_off_stops_a_goal_run_and_on_reruns_it(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    view.composer.fill(read_goal() + work_on(bash('sleep 8') + say('Checked every venue.'))
                       + choose('continue', 'Checking the venues next.') + say('Starting the venue check.'))
    page.get_by_role('button', name='Send message', exact=True).click()
    view.until(lambda: view.transitions().count('run') == 2 and view.current()['claim'] is not None)
    view.set_goals(False)
    view.until(lambda: view.active_run() is None)
    page.wait_for_timeout(1500)
    assert view.transitions().count('run') == 2
    assert view.active_run() is None
    view.set_goals(True)
    view.until(lambda: view.transitions().count('run') == 3, timeout=5)
    wakeups = [e for e in view.events() if e['type'] == 'goal' and e['data']['kind'] == 'wakeup']
    assert wakeups[-1]['data']['reason'] == 'interrupted'
    assert wakeups[-1]['data']['wake_id'] == wakeups[-2]['data']['wake_id']


def test_goals_off_returns_a_queued_message_to_the_composer(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    view.composer.fill(read_goal() + bash('sleep 8') + say('Checked every venue.'))
    page.get_by_role('button', name='Send message', exact=True).click()
    expect(page.get_by_test_id('chat-stop-btn')).to_be_visible(timeout=8000)
    expect(view.composer).to_have_attribute('placeholder', 'Message the agent while it works…', timeout=8000)
    view.composer.fill('Also check the library hall')
    page.get_by_role('button', name='Send message', exact=True).click()
    strip = page.get_by_role('region', name="Queued for the agent's next step")
    expect(strip).to_contain_text('Also check the library hall')
    view.set_goals(False)
    expect(strip).to_have_count(0, timeout=10000)
    expect(view.composer).to_have_value('Also check the library hall')
    assert not any(e['type'] == 'user_message' and e['content'] == 'Also check the library hall' for e in view.events())


def test_goal_routes_refuse_after_goals_turn_off_in_another_tab(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    view.open()
    other = page.context.new_page()
    try:
        SettingsPage(other).goto_system()
        SettingsPage(other).unlock_early_access()
        other.get_by_test_id('goals-toggle').click()
        expect(other.get_by_role('switch', name='Goals', exact=True)).not_to_be_checked()
    finally:
        other.close()
    view.details.get_by_role('button', name='Pause', exact=True).click()
    expect(view.details).to_contain_text('Goals are turned off.')
    refused = page.request.post(view.base + '/pause', data={})
    assert refused.status == 403
    assert refused.json()['error'] == 'Goals are turned off.'
    view.set_goals(True)
    assert view.current()['paused'] is False
