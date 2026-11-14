"""Goal UI actions and bounded observations of the real application."""

import json
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from playwright.sync_api import Page, expect

from tests.e2e._protocol import call_tool, say
from tests.e2e.pages.chat_view import ChatView


def future(minutes: float = 30) -> str:
    """An ISO time this many minutes from now."""
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def read_goal() -> str:
    """Every goal write is refused until the run has read the goal."""
    return call_tool('read_goal')


def update_goal(**fields: object) -> str:
    return call_tool('update_goal', **fields)


def update_questions(*changes: dict) -> str:
    return call_tool('update_goal_questions', changes=list(changes))


def choose(action: str, note: str = 'Saved the next step.', **fields: object) -> str:
    return call_tool('choose_next_action', action=action, note=note, **fields)


def work_on(step_script: str, step_id: str = 'check') -> str:
    """Put a step in progress whose title scripts the next wake run.

    A wake run's start note names the step in progress, and the fake model
    reads its directives from that note.
    """
    return update_goal(plan=[{'id': step_id, 'title': step_script, 'status': 'in_progress'}])


@contextmanager
def goal_conversation(page: Page):
    """Turn Goals on, open a new chat with one finished turn, and clean up afterwards."""
    settings = page.request.get('/api/settings').json()
    assert page.request.put('/api/settings', data={'goals_enabled': True}).ok
    captured = {}
    page.on('request', lambda request: captured.update(json.loads(request.post_data))
            if request.method == 'POST' and request.url.endswith('/api/chat') else None)
    ChatView(page).goto().new_conversation().send(say('Ready for a goal.')).wait_streaming()
    view = GoalsView(page, captured['conversation_id'], settings['default_agent'])
    try:
        yield view
    finally:
        page.unroute_all(behavior='ignoreErrors')
        page.request.put('/api/settings', data={'goals_enabled': True})
        page.request.post(view.base + '/cancel', data={})
        page.request.post(f'/api/chat/stop?conversation_id={view.conversation_id}')
        page.request.delete(f'/api/conversations/sessions/{view.conversation_id}')
        page.request.put('/api/settings', data={'goals_enabled': settings.get('goals_enabled', False)})


class GoalsView:
    def __init__(self, page: Page, conversation_id: str, profile_id: str):
        self.page = page
        self.conversation_id = conversation_id
        self.profile_id = profile_id
        self.base = f'/api/conversations/sessions/{conversation_id}/goal'

    @property
    def composer(self):
        return self.page.get_by_role('textbox', name='Message', exact=True)

    @property
    def details(self):
        return self.page.get_by_test_id('goal-details')

    @property
    def header(self):
        """The chat header's goal status button."""
        return self.page.get_by_role('button', name='Open goal details', exact=True)

    @property
    def questions(self):
        return self.page.get_by_label('Goal questions', exact=True)

    def dividers(self, transition: str | None = None):
        dividers = self.page.get_by_test_id('goal-transition')
        if transition is None:
            return dividers
        return self.page.locator(f'[data-testid="goal-transition"][data-transition="{transition}"]')

    def current(self):
        response = self.page.request.get(self.base)
        assert response.ok, response.text()
        return response.json()['goal']

    def wait(self, predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while True:
            goal = self.current()
            if goal and predicate(goal):
                return goal
            assert time.monotonic() < deadline, f'Goal did not reach expected state: {goal}'
            self.page.wait_for_timeout(100)

    def idle(self, timeout=15):
        """Wait until a run has happened and no run owns the goal or is due right now."""
        def settled(goal):
            due = goal['next']['kind'] == 'wake' and not goal['paused'] and (
                datetime.fromisoformat(goal['next']['at']) <= datetime.now(timezone.utc))
            return goal['last_run_id'] and not goal['running'] and goal['claim'] is None and not due
        return self.wait(settled, timeout)

    def events(self):
        response = self.page.request.post(f'/api/conversations/sessions/{self.conversation_id}/resume')
        assert response.ok, response.text()
        return response.json()['events']

    def transitions(self):
        """Goal divider kinds in transcript order, with goal runs as 'run'."""
        return [e['data']['kind'] if e['data']['kind'] != 'wakeup' else 'run'
                for e in self.events() if e['type'] == 'goal' and e['data']['kind'] != 'state_notice']

    def shown(self):
        """Goal divider kinds as drawn in the chat, top to bottom."""
        return [divider.get_attribute('data-transition') for divider in self.dividers().all()]

    def chat(self):
        self.page.get_by_test_id('view-tab-destination:conversation').click()

    def open(self):
        self.chat()
        self.header.click()
        expect(self.details).to_be_visible()

    def close(self):
        self.page.get_by_test_id('view-tab-actions-goal').click()
        self.page.get_by_role('menuitem', name='Close tab', exact=True).click()
        self.chat()

    def more_actions(self, item: str):
        self.details.get_by_role('button', name='More goal actions', exact=True).click()
        self.page.get_by_role('menuitem', name=item).click()

    def cancel(self):
        self.more_actions('Cancel goal')
        self.page.get_by_role('menuitem', name='Cancel this goal?').click()
        return self.wait(lambda g: g['next']['kind'] == 'cancelled')

    def open_assignment(self, entry='plus', objective=''):
        self.chat()
        if entry == 'slash':
            self.composer.fill('/goal ' + objective)
            self.page.get_by_role('button', name='Send message', exact=True).click()
        else:
            self.page.get_by_role('button', name='Add to chat', exact=True).click()
            self.page.get_by_role('menuitem', name='Start a goal… /goal', exact=True).click()
        dialog = self.page.get_by_role('dialog', name='Start a goal')
        expect(dialog).to_be_visible()
        return dialog

    def assign(self, objective='Keep the community calendar current', entry='plus'):
        """Start a goal through the UI and wait for its first run.

        The first run has no plan step and chooses nothing, so the goal then waits for the user.
        """
        dialog = self.open_assignment(entry, objective)
        if entry == 'slash':
            expect(dialog.get_by_label('What would you like done?')).to_have_value(objective)
        else:
            dialog.get_by_label('What would you like done?').fill(objective)
        dialog.get_by_role('button', name='Start goal', exact=True).click()
        expect(dialog).to_have_count(0)
        goal = self.idle()
        assert goal['objective'] == objective
        assert goal['next'] == {'kind': 'wait', 'question_ids': []}, goal
        return goal

    def send(self, directives, answer='Agent finished this step.'):
        """Send a chat message and wait for its reply and for any run it set up to finish."""
        self.chat()
        show = self.page.get_by_role('button', name='Show goal questions', exact=True)
        if self.questions.is_visible():
            self.questions.get_by_role('button', name='Hide', exact=True).click()
            expect(show).to_be_visible()
        self.composer.fill(directives + say(answer))
        self.page.get_by_role('button', name='Send message', exact=True).click()
        expect(self.page.get_by_test_id('message-assistant').filter(has_text=answer).last).to_be_visible(timeout=15000)
        goal = self.idle()
        if show.is_visible():
            show.click()
        return goal

    def background(self, directives):
        """Run a chat turn through the API while the page stays as it is."""
        response = self.page.request.post('/api/chat', data={
            'conversation_id': self.conversation_id, 'profile_id': self.profile_id, 'message': directives,
        })
        assert response.ok, response.text()
        return self.idle()

    def schedule(self, step_script, at=None, note='I will check again later.', answer='Scheduled the next check.'):
        """Plan a later wake run that runs ``step_script``."""
        return self.send(read_goal() + work_on(step_script) + choose('schedule', note, at=at or future(24 * 60)), answer)

    def ask(self, *, wait=True, choices=None):
        changes = [
            {'id': 'day', 'question': 'Which day works for you?', 'choices': choices or ['Saturday', 'Sunday']},
            {'id': 'place', 'question': 'Where should we meet?'},
        ]
        script = read_goal() + update_questions(*changes)
        if wait:
            script += choose('wait_for_input', 'I need two answers first.', question_ids=['day', 'place'])
        self.send(script, 'I have two questions before arranging the event.')
        expect(self.questions).to_be_visible(timeout=10000)
        return self.current()
