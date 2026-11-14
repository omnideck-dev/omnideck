"""Goal questions stay in the composer and answers travel through real chat runs."""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._protocol import say, slow
from tests.e2e.pages import ChatView
from tests.e2e.pages.goals_view import (
    choose, goal_conversation, read_goal, update_goal, update_questions, work_on,
)


@pytest.fixture
def goal_ui(page: Page):
    with goal_conversation(page) as view:
        yield view


def tab_group(locator) -> str:
    return locator.locator('xpath=ancestor::section[@data-tab-group-id]').get_attribute('data-tab-group-id')


def expand_history_details(history) -> None:
    """Open every folded run so each change is readable."""
    folds = history.locator('summary').filter(has_text='Details')
    for index in range(folds.count()):
        folds.nth(index).click()


def test_goal_wakeup_instructions_stay_hidden_live_and_after_reload(goal_ui):
    view, page = goal_ui, goal_ui.page
    view.assign()
    answer = 'The school calendar is up to date.'
    view.send(read_goal() + work_on(say(answer)) + choose('continue', 'Checking the calendar next.'), 'Checking now.')
    expect(page.get_by_test_id('message-assistant').filter(has_text=answer)).to_be_visible(timeout=15000)
    view.idle()
    wakeups = [e for e in view.events() if e['type'] == 'goal' and e['data']['kind'] == 'wakeup']
    assert len(wakeups) == 2
    # Wake runs show as dividers, never as messages from the user. The first run
    # starts with the goal, so only the second gets its own divider.
    users = page.get_by_test_id('message-user')
    expect(users).to_have_count(2)
    expect(users.filter(has_text='[System activity')).to_have_count(0)
    expect(view.dividers('run')).to_have_count(1)
    expect(page.get_by_test_id('goal-wakeup')).to_have_count(0)
    page.reload()
    expect(page.get_by_test_id('message-assistant').filter(has_text=answer)).to_be_visible()
    expect(users).to_have_count(2)
    expect(users.filter(has_text='[System activity')).to_have_count(0)
    expect(view.dividers('run')).to_have_count(1)


def test_goal_question_carousel_submits_all_drafts_and_preserves_transcript(goal_ui, output_path: str) -> None:
    view, page = goal_ui, goal_ui.page
    view.assign('Find and book a dentist')
    view.send(read_goal() + update_questions(
        {'id': 'insurance', 'question': 'Which insurance plan?', 'choices': ['Aetna Dental PPO']},
        {'id': 'travel', 'question': 'How far can you travel?'},
    ) + choose('wait_for_input', 'I need your insurance and travel limits.', question_ids=['insurance', 'travel']),
        'I have two questions.')
    expect(view.questions).to_be_visible(timeout=10000)
    expect(view.composer).to_have_count(1)
    expect(page.get_by_test_id('chat-title-bar')).to_be_visible()
    expect(page.locator('[data-section="needs-you"]')).to_contain_text('2 questions for you')
    composer_form = view.composer.locator('xpath=ancestor::form')
    expect(composer_form.get_by_test_id('goal-panel')).to_have_count(0)
    expect(page.get_by_test_id('chat-title-bar').get_by_test_id('goal-details')).to_have_count(0)
    view.open()
    goal_tab = page.get_by_test_id('view-tab-goal')
    chat_tab = page.get_by_test_id('view-tab-destination:conversation')
    assert tab_group(goal_tab) != tab_group(chat_tab)
    expect(view.composer).to_be_visible()
    view.close()
    page.get_by_role('button', name='Hide', exact=True).click()
    expect(view.questions).to_have_count(0)
    expect(composer_form.get_by_text('2 questions for you', exact=True)).to_be_visible()
    view.composer.fill('A separate chat draft')
    view.open()
    expect(view.questions).to_have_count(0)
    view.close()
    expect(view.composer).to_have_value('A separate chat draft')
    page.get_by_role('button', name='Show goal questions').click()
    expect(view.questions).to_be_visible()
    expect(view.composer).to_have_value('')

    for width, label in [(1280, 'desktop'), (390, 'mobile')]:
        page.set_viewport_size({'width': width, 'height': 900})
        if width == 390:
            page.get_by_role('button', name='Collapse sidebar', exact=True).click()
            expect(page.get_by_test_id('sidebar')).to_have_css('width', '44px')
        expect(view.questions).to_be_visible()
        box = view.questions.bounding_box()
        assert box and box['x'] >= 0 and box['x'] + box['width'] <= width
        for name in ['Send answer', 'Skip for now']:
            control = page.get_by_role('button', name=name, exact=True).bounding_box()
            assert control and control['x'] >= 0 and control['x'] + control['width'] <= width
        expand = page.get_by_test_id('composer-expand-btn')
        if expand.is_visible():
            expand_box = expand.bounding_box()
            skip_box = page.get_by_role('button', name='Skip for now').bounding_box()
            assert expand_box['y'] >= skip_box['y'] + skip_box['height']
        page.screenshot(path=str(Path(output_path) / f'goal-questions-{label}.png'))
    page.set_viewport_size({'width': 1280, 'height': 900})
    page.get_by_role('button', name='Expand sidebar', exact=True).click()
    # A choice marks the answer and moves on; it never fills the text box.
    page.get_by_role('button', name='Aetna Dental PPO', exact=True).click()
    expect(view.questions).to_contain_text('How far can you travel?')
    expect(view.composer).to_have_value('')
    view.composer.fill('Within 10 miles')
    expect(view.questions.get_by_role('button', name='Question 2, answer drafted')).to_be_visible()
    view.questions.get_by_role('button', name='Question 1, answer drafted').click()
    expect(page.get_by_role('button', name='Aetna Dental PPO', exact=True)).to_have_attribute('aria-pressed', 'true')
    expect(view.composer).to_have_value('')
    page.reload()
    expect(page.get_by_role('button', name='Aetna Dental PPO', exact=True)).to_have_attribute('aria-pressed', 'true')
    # Both saved drafts are submitted together, independent of the visible question.
    page.get_by_role('button', name='Send 2 answers').click()
    expect(page.get_by_test_id('message-user').last).to_contain_text('Aetna Dental PPO')
    expect(page.get_by_test_id('message-user').last).to_contain_text('Which insurance plan?')
    expect(view.questions).to_have_count(0, timeout=10000)
    reply = next(event for event in view.events() if event['type'] == 'user_message' and event.get('context'))
    assert [item['question_id'] for item in reply['context']] == ['insurance', 'travel']
    assert [item['answer'] for item in reply['context']] == ['Aetna Dental PPO', 'Within 10 miles']
    pairs = page.get_by_test_id('message-user').last.get_by_test_id('goal-question-answer')
    expect(pairs).to_have_count(2)
    expect(pairs.nth(0)).to_contain_text('Which insurance plan?')
    expect(pairs.nth(0)).to_contain_text('Aetna Dental PPO')
    expect(pairs.nth(0)).not_to_contain_text('Within 10 miles')
    expect(pairs.nth(1)).to_contain_text('How far can you travel?')
    expect(pairs.nth(1)).to_contain_text('Within 10 miles')
    view.idle()
    current = view.current()
    assert current['questions'][0]['answers'][0]['answer'] == 'Aetna Dental PPO'
    assert current['questions'][0]['status'] == 'open'
    assert current['questions'][1]['answers'][0]['answer'] == 'Within 10 miles'
    expect(page.get_by_test_id('message-user').filter(has_text='[System activity')).to_have_count(0)
    # The agent resolves one question and withdraws the other; only goal history shows these updates.
    view.background(read_goal() + update_questions(
        {'id': 'insurance', 'status': 'resolved'}, {'id': 'travel', 'status': 'withdrawn'},
    ) + update_goal(summary='Insurance: Aetna Dental PPO. Search the local area.') + say('The plan is recorded.'))
    page.reload()
    expect(view.questions).to_have_count(0)
    expect(page.get_by_role('button', name='Show goal questions')).to_have_count(0)
    saved_pairs = page.get_by_test_id('message-user').filter(has_text='Within 10 miles').get_by_test_id('goal-question-answer')
    expect(saved_pairs).to_have_count(2)
    expect(saved_pairs.nth(0)).to_contain_text('Which insurance plan?')
    expect(saved_pairs.nth(0)).to_contain_text('Aetna Dental PPO')
    expect(saved_pairs.nth(1)).to_contain_text('How far can you travel?')
    expect(saved_pairs.nth(1)).to_contain_text('Within 10 miles')
    page.screenshot(path=str(Path(output_path) / 'goal-answer-pairs.png'))
    expect(page.get_by_label('Goal question update')).to_have_count(0)
    view.open()
    expect(view.details.get_by_role('region', name='What the agent knows')).to_contain_text('Insurance: Aetna Dental PPO.')
    view.more_actions('Open goal history')
    history = page.get_by_role('region', name='Goal history entries')
    expect(history).to_contain_text('Answered: Which insurance plan?', timeout=10000)
    expect(history).to_contain_text('Aetna Dental PPO')
    expand_history_details(history)
    expect(history).to_contain_text('Withdrawn.')
    expect(history).to_contain_text('Resolved.')


def test_goal_history_loads_older_work_on_demand_and_keeps_current_state_small(goal_ui, output_path: str) -> None:
    view, page = goal_ui, goal_ui.page
    history_requests = []
    page.on('request', lambda request: history_requests.append(request.url) if '/goal/history?' in request.url else None)
    view.assign('Grow the neighborhood newsletter')
    view.send(read_goal() + update_questions({'id': 'budget', 'question': 'What is the monthly budget?'})
              + choose('wait_for_input', 'I need the budget first.', question_ids=['budget']), 'What is the budget?')
    for index in range(12):
        view.background(read_goal() + update_goal(summary=f'Campaign review {index}: checked signups')
                        + choose('wait_for_input', f'Finished campaign review {index}.', question_ids=['budget'])
                        + say(f'Review {index} done.'))
    view.background(read_goal() + update_goal(
        summary='Library referrals brought in new subscribers. Continue the partnership.',
        plan=[{'id': 'library', 'title': 'Expand the library partnership'}],
    ) + say('Saved the partnership plan.'))
    page.reload()
    view.open()
    expect(view.details.get_by_role('region', name='What the agent knows')).to_contain_text(
        'Library referrals brought in new subscribers. Continue the partnership.')
    assert history_requests == []
    view.more_actions('Open goal history')
    history = page.get_by_role('region', name='Goal history entries')
    expect(history.get_by_text('Finished campaign review 11.', exact=True)).to_be_visible()
    expect(history.get_by_text('Finished campaign review 0.', exact=True)).to_have_count(0)
    assert len(history_requests) == 1
    history.get_by_role('button', name='Load older entries').click()
    expect(history.get_by_text('Finished campaign review 0.', exact=True)).to_be_attached()
    history.get_by_role('searchbox', name='Search goal history').fill('Campaign review 0:')
    expect(page.get_by_test_id('goal-history-entry')).to_have_count(1)
    expand_history_details(history)
    expect(history).to_contain_text('Campaign review 0: checked signups')
    expect(history).not_to_contain_text('Campaign review 11')
    expect(history.get_by_role('button', name='Refresh')).to_have_count(0)
    page.screenshot(path=str(Path(output_path) / 'goal-history-search.png'))
    snapshot = view.current()
    assert 'progress' not in snapshot and 'progress_count' not in snapshot
    assert snapshot['history_count'] >= 25
    assert snapshot['summary'].startswith('Library referrals')
    assert snapshot['note'] == 'Finished campaign review 11.'


def test_goal_layout_keeps_editor_actions_and_long_questions_within_viewport(goal_ui) -> None:
    """Long goal content stays usable in a small pane and a short viewport."""
    view, page = goal_ui, goal_ui.page
    title = 'Review both connected mailboxes and their existing spam and junk folders'
    choice = 'Keep anything ambiguous in my inbox and ask me before moving it'
    view.assign('Keep my inbox free of spam')
    plan = [{'id': f's{i}', 'title': f'{title} {i + 1}', 'status': 'done' if i < 5 else 'in_progress',
             'notes': 'Keep receipts, personal messages, and anything ambiguous in the inbox. ' * 4} for i in range(6)]
    view.send(read_goal() + update_goal(plan=plan) + update_questions(
        {'id': 'spam', 'question': 'How should I handle promotional messages that might include a receipt or a personal update?', 'choices': [choice]},
        {'id': 'next', 'question': 'How often should I check?'},
    ) + choose('wait_for_input', 'I need to know how to handle promotions.', question_ids=['spam']), 'I have a question.')
    expect(view.questions).to_be_visible()
    for width, height in [(1280, 900), (768, 700), (390, 700), (320, 568)]:
        page.set_viewport_size({'width': width, 'height': height})
        collapse = page.get_by_role('button', name='Collapse sidebar', exact=True)
        if width < 500 and collapse.is_visible():
            collapse.click()
            expect(page.get_by_test_id('sidebar')).to_have_css('width', '44px')
        for name in [choice, 'Skip for now', 'Hide', 'Send answer']:
            box = page.get_by_role('button', name=name, exact=True).bounding_box()
            assert box and box['x'] >= 0 and box['x'] + box['width'] <= width, name
        header = page.get_by_test_id('chat-title-bar')
        assert header.bounding_box()['height'] == 44
        assert header.evaluate('(e) => e.scrollWidth <= e.clientWidth')
        view.open()
        view.details.get_by_role('button', name='Edit', exact=True).click()
        dialog = page.get_by_role('dialog', name='Edit', exact=True)
        expect(dialog).to_be_visible()
        expect(dialog.locator('summary').filter(has_text='Plan').first).to_be_visible()
        expect(dialog.get_by_label('Step 1 title')).to_be_hidden()
        dialog.locator('summary').filter(has_text='Plan').first.click()
        dialog.locator('summary').filter(has_text=title + ' 1').click()
        save = dialog.get_by_role('button', name='Save changes')
        before = save.bounding_box()
        assert before and before['y'] + before['height'] <= height - 16
        field = dialog.get_by_label('Step 1 title')
        field_box, dialog_box = field.bounding_box(), dialog.bounding_box()
        assert field_box['x'] >= dialog_box['x'] + 16
        assert field_box['x'] + field_box['width'] <= dialog_box['x'] + dialog_box['width'] - 16
        # Scrolling the body to its last control must not scroll the footer.
        dialog.get_by_role('button', name='Add step').click()
        expect(dialog.get_by_label('Step 7 title')).to_be_visible()
        after = save.bounding_box()
        assert abs(before['y'] - after['y']) <= 1
        dialog.get_by_role('button', name='Cancel', exact=True).click()
        view.close()
        page.get_by_role('button', name='Toggle theme').click()
    # Goal details have their own view, even while the composer is expanded.
    view.composer.fill('An answer\nwith several\nlines of detail')
    page.get_by_role('button', name='Expand input', exact=True).click()
    view.open()
    details = view.details.bounding_box()
    assert details and details['height'] > 300 and details['y'] >= 8
    view.close()
    page.get_by_role('button', name='Conversation details', exact=True).click()
    expect(page.get_by_role('region', name='Conversation details')).to_be_visible()
    expect(page.get_by_role('region', name='Conversation details').get_by_role('button', name='Open conversation artifacts')).to_be_visible()


def test_goal_tab_follows_selected_chat_restores_and_keeps_chat_draft(goal_ui, output_path: str) -> None:
    view, page = goal_ui, goal_ui.page
    view.assign('Grow the neighborhood newsletter')
    view.send(read_goal() + update_goal(
        summary='The library partnership is bringing in more readers. Keep testing useful local stories.',
        plan=[{'id': 'review', 'title': 'Review where new readers came from', 'status': 'done'},
              {'id': 'edition', 'title': 'Prepare the next edition', 'notes': 'Keep the content useful and easy to skim.'}],
    ), 'Planned the next edition.')
    assert page.request.post(view.base + '/pause', data={}).ok
    page.reload()
    expect(page.get_by_test_id('sidebar')).to_contain_text('Paused')
    # Selecting a goal conversation shows status without opening a details tab.
    expect(view.header).to_contain_text('Paused')
    expect(page.get_by_test_id('view-tab-goal')).to_have_count(0)
    page.get_by_test_id('sidebar').get_by_test_id('goal-status').click()
    expect(page.get_by_test_id('view-tab-goal')).to_have_count(0)
    expect(page.get_by_role('button', name=re.compile(r'^View goal for '))).to_have_count(0)
    view.composer.fill('Keep this unsent thought')
    view.open()
    expect(view.composer).to_be_visible()
    expect(view.composer).to_have_value('Keep this unsent thought')
    expect(view.details.get_by_role('button', name='Resume', exact=True)).to_be_visible()
    expect(view.details.get_by_test_id('goal-reason')).to_contain_text('When you resume')
    # The chat is visible beside the Goal tab, so the tab offers no Open chat.
    expect(view.details.get_by_role('button', name='Open chat')).to_have_count(0)
    view.open()
    expect(page.get_by_test_id('view-tab-goal')).to_have_count(1)
    expect(page.get_by_test_id('view-tab-goal')).to_contain_text('Goal · ')
    page.screenshot(path=str(Path(output_path) / 'goal-tab-light.png'), animations='disabled')
    page.get_by_role('button', name='Toggle theme').click()
    page.screenshot(path=str(Path(output_path) / 'goal-tab-dark.png'), animations='disabled')
    page.reload()
    expect(view.details).to_be_visible()
    expect(view.composer).to_have_value('Keep this unsent thought')
    view.close()
    view.composer.fill('/goal')
    page.get_by_role('button', name='Send message', exact=True).click()
    expect(view.details).to_be_visible()
    expect(view.composer).to_have_value('')
    # The one Goal tab follows the selected chat.
    view.chat()
    ChatView(page).new_conversation()
    expect(page.get_by_test_id('view-tab-goal')).to_have_count(1)
    expect(view.details).to_contain_text('This chat has no goal')
    expect(view.details.get_by_role('button', name='Start a goal…')).to_be_visible()
    expect(view.details).not_to_contain_text('Grow the neighborhood newsletter')
    page.get_by_test_id('sidebar').get_by_test_id('goal-status').first.click()
    expect(view.details).to_contain_text('Grow the neighborhood newsletter')
    # Mobile uses one reachable tab group rather than a hidden side pane.
    view.close()
    page.set_viewport_size({'width': 390, 'height': 844})
    page.get_by_role('button', name='Collapse sidebar', exact=True).click()
    expect(page.get_by_test_id('sidebar')).to_have_css('width', '44px')
    view.open()
    assert view.details.evaluate('(e) => e.scrollWidth <= e.clientWidth')
    assert tab_group(page.get_by_test_id('view-tab-goal')) == tab_group(page.get_by_test_id('view-tab-destination:conversation'))
    page.screenshot(path=str(Path(output_path) / 'goal-tab-mobile.png'), animations='disabled')
    view.details.get_by_role('button', name='Open chat').click()
    expect(view.composer).to_be_visible()
    expect(page.get_by_test_id('message-assistant').filter(has_text='Planned the next edition.')).to_be_visible()


def test_goal_headline_shows_each_status_with_long_plan_text(goal_ui, output_path: str) -> None:
    """Compact status in the header, with long plan text only on hover."""
    view, page = goal_ui, goal_ui.page
    step = ('Search live openings for Senior Director / VP Engineering in Austin, remote OR hybrid; '
            'capture company, compensation, requirements, and application links.')
    view.assign('Find a new role')
    headline = view.header

    def check(name, label):
        expect(headline).to_be_visible()
        expect(headline).to_contain_text(label)
        expect(headline).not_to_contain_text(step)
        assert headline.bounding_box()['width'] < 360
        page.screenshot(path=str(Path(output_path) / f'goal-headline-{name}.png'), animations='disabled')

    view.composer.fill(read_goal() + update_goal(plan=[
        {'id': 'first', 'title': 'Review preferences', 'status': 'done'},
        {'id': 'search', 'title': step, 'status': 'in_progress'},
    ]) + slow() + say('Searching the listings now. ' * 120))
    page.get_by_role('button', name='Send message', exact=True).click()
    sidebar_status = page.get_by_test_id('sidebar').get_by_test_id('goal-status')
    expect(sidebar_status).to_have_text('Working', timeout=8000)
    check('working', 'Working')
    expect(sidebar_status).to_have_attribute('title', re.compile('Search live openings'))
    expect(headline).to_have_attribute('title', re.compile('1 of 2 steps done.*Search live openings'))
    page.get_by_test_id('chat-stop-btn').click()
    view.idle()

    view.send(read_goal() + update_questions(
        {'id': 'q1', 'question': 'Which roles should I pursue?'},
        {'id': 'q2', 'question': 'What is your preferred location?'},
    ) + choose('wait_for_input', 'I need your role and location preferences.', question_ids=['q1', 'q2']), 'Two questions.')
    check('questions', '2 questions for you')
    page.set_viewport_size({'width': 390, 'height': 844})
    collapse = page.get_by_role('button', name='Collapse sidebar', exact=True)
    if collapse.is_visible():
        collapse.click()
    expect(headline.get_by_text('2 questions', exact=True)).to_be_visible()
    expect(headline.get_by_text('2 questions for you', exact=True)).to_be_hidden()
    assert page.get_by_test_id('chat-title-bar').evaluate('(e) => e.scrollWidth <= e.clientWidth')
    page.screenshot(path=str(Path(output_path) / 'goal-headline-questions-mobile.png'), animations='disabled')
    page.set_viewport_size({'width': 1280, 'height': 720})

    view.send(read_goal() + update_questions({'id': 'q1', 'status': 'withdrawn'}, {'id': 'q2', 'status': 'withdrawn'})
              + choose('schedule', 'Searching again next week.', at='2099-01-05T15:00:00Z'), 'Scheduled.')
    check('scheduled', 'Resumes')

    assert page.request.post(view.base + '/pause', data={}).ok
    check('paused', 'Paused')


def test_goal_lifecycle_dividers_survive_reload_and_fit_narrow_chat(goal_ui, output_path: str) -> None:
    view, page = goal_ui, goal_ui.page
    objective = 'Keep our community calendar current, including school dates, library events, and neighborhood meetings'
    assigned = page.request.post(view.base, data={'objective': objective, 'profile_id': view.profile_id})
    assert assigned.ok
    view.idle()
    assert page.request.post(view.base + '/pause', data={}).ok
    assert page.request.post(view.base + '/pause', data={}).status == 409
    expect(view.dividers('started')).to_contain_text('Goal started', timeout=15000)
    expect(view.dividers('paused')).to_have_count(1)
    assert page.request.post(view.base + '/cancel', data={}).ok
    expect(view.dividers('cancelled')).to_contain_text('Goal cancelled', timeout=15000)
    labels = ['Goal started', 'Waiting for you', 'Paused', 'Goal cancelled']
    expect(view.dividers()).to_have_count(len(labels))
    for index, label in enumerate(labels):
        expect(view.dividers().nth(index)).to_contain_text(label)
    # Each divider's time shows only on hover.
    started = view.dividers('started')
    time = started.locator('time')
    expect(time).to_have_css('opacity', '0')
    started.hover()
    expect(time).to_have_css('opacity', '1')
    page.mouse.move(0, 0)
    before = view.dividers().all_text_contents()
    page.screenshot(path=str(Path(output_path) / 'goal-lifecycle-desktop.png'))
    page.reload()
    expect(view.dividers()).to_have_count(len(labels))
    assert view.dividers().all_text_contents() == before
    page.set_viewport_size({'width': 390, 'height': 844})
    collapse = page.get_by_role('button', name='Collapse sidebar', exact=True)
    if collapse.is_visible():
        collapse.click()
    started.scroll_into_view_if_needed()
    box = started.bounding_box()
    assert box['x'] >= 0 and box['x'] + box['width'] <= 390
    assert started.evaluate('(node) => node.scrollWidth <= node.clientWidth')
    page.screenshot(path=str(Path(output_path) / 'goal-lifecycle-mobile.png'))


def test_scheduled_return_uses_one_wake_record_live_and_after_reload(goal_ui) -> None:
    view, page = goal_ui, goal_ui.page
    view.assign('Keep the calendar current')
    answer = 'I checked the calendar on schedule.'
    at = (datetime.now(timezone.utc) + timedelta(seconds=3)).isoformat()
    scheduled = view.send(read_goal() + work_on(say(answer)) + choose('schedule', 'Checking again shortly.', at=at),
                          'I will check in a moment.')
    wake_id = scheduled['next']['id']
    expect(page.get_by_test_id('message-assistant').filter(has_text=answer)).to_be_visible(timeout=20000)
    view.idle()
    returned = view.dividers('run')
    expect(returned).to_have_count(1)
    expect(returned.last).to_contain_text(answer)
    wakes = [e for e in view.events() if e['type'] == 'goal' and e['data']['kind'] == 'wakeup' and e['data']['wake_id'] == wake_id]
    assert len(wakes) == 1 and wakes[0]['data']['reason'] == 'planned'
    assert view.transitions() == ['started', 'run', 'waiting', 'scheduled', 'run', 'waiting']
    page.reload()
    expect(returned).to_have_count(1)
    expect(page.get_by_test_id('message-assistant').filter(has_text=answer)).to_be_visible()
