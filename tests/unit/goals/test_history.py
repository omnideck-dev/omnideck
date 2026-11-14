"""Long-running goal recall, bounded state and atomic journal writes."""

import json

import pytest

from goals import GoalAnswerSubmission, GoalQuestionChange, GoalStep, GoalStore

from tests.unit.goals.support import ask, chat_turn, claim_wake


def save_summary(store, goal_id, summary):
    current = store.get(goal_id)
    return store.update(goal_id, current.revision, summary=summary)


def pages(store, goal_id, query=''):
    entries, cursor = [], None
    while True:
        page = store.read_history(goal_id, query, cursor)
        entries.extend(page['entries'])
        cursor = page['next_before']
        if cursor is None:
            return entries


def change_question(store, goal_id, change):
    current = store.get(goal_id)
    return store.update_questions(goal_id, [change], current.revision, claim_id='claim')


def test_long_history_stays_retrievable_without_growing_working_state(tmp_path):
    store = GoalStore(tmp_path)
    goal = store.create('chat', 'Grow website traffic', 'assistant')
    for index in range(1000):
        goal = save_summary(store, goal.id, f'Campaign {index}: result {index}')
    assert goal.summary == 'Campaign 999: result 999'
    assert len(goal.model_dump_json()) < 10000
    restored = GoalStore(tmp_path).get(goal.id)
    assert restored.summary == goal.summary
    entries = pages(store, goal.id, 'Campaign')
    assert len(entries) == len({entry['id'] for entry in entries}) == 1000
    assert entries[-1]['data']['after']['summary'] == 'Campaign 0: result 0'
    assert store.read_history(goal.id, 'Campaign 17:')['entries'][0]['data']['after']['summary'] == 'Campaign 17: result 17'
    assert store.read_history(goal.id, '%')['entries'] == []  # literal search


def test_history_cursor_is_stable_when_new_entries_arrive(tmp_path):
    store = GoalStore(tmp_path)
    goal = store.create('chat', 'Goal', 'assistant')
    for index in range(40):
        save_summary(store, goal.id, f'Entry {index}')
    first = store.read_history(goal.id, 'Entry')
    save_summary(store, goal.id, 'Entry arriving during pagination')
    second = store.read_history(goal.id, 'Entry', first['next_before'])
    ids = [entry['id'] for entry in first['entries'] + second['entries']]
    assert len(ids) == len(set(ids)) == 40
    assert second['next_before'] is None


def test_plan_entries_show_change_lines_and_keep_full_plans_on_disk(tmp_path):
    store = GoalStore(tmp_path)
    goal = store.create('chat', 'Goal', 'assistant')
    goal = store.update(goal.id, goal.revision, plan=[GoalStep(id='ads', title='Try paid ads')])
    goal = store.update(goal.id, goal.revision, plan=[GoalStep(id='referrals', title='Ask for referrals')])
    goal = store.update(goal.id, goal.revision, summary='Paid ads failed. Try referrals next.')
    goal = store.update(goal.id, goal.revision, summary='Referrals are working. Expand the program.')
    on_disk = [entry for entry in store._files.entries(goal, 0) if entry['kind'] == 'plan']
    assert on_disk[0]['data']['before']['plan'][0]['id'] == 'ads'
    assert on_disk[0]['data']['after']['plan'][0]['id'] == 'referrals'
    shown = [entry for entry in pages(store, goal.id) if entry['kind'] == 'plan']
    assert shown[0]['data'] == {'changes': ['Removed "Try paid ads".', 'Added "Ask for referrals".']}
    checkpoints = store.read_history(goal.id, 'Paid ads failed')['entries']
    assert len(checkpoints) == 1
    assert checkpoints[0]['data'] == {'after': {'summary': 'Paid ads failed. Try referrals next.'}}
    assert goal.summary == 'Referrals are working. Expand the program.'


def test_plan_change_lines_describe_each_step_change(tmp_path):
    store = GoalStore(tmp_path)
    goal = store.create('chat', 'Goal', 'assistant')
    goal = store.update(goal.id, goal.revision, plan=[
        GoalStep(id='call', title='Call the parks office'), GoalStep(id='pay', title='Pay the deposit'),
    ])
    goal = store.update(goal.id, goal.revision, plan=[
        GoalStep(id='call', title='Call the parks office again', status='done', notes='Booked 11 AM to 4 PM'),
        GoalStep(id='pay', title='Pay the deposit', depends_on=['call']),
    ])
    lines = pages(store, goal.id)[0]['data']['changes']
    assert lines == [
        'Renamed "Call the parks office" to "Call the parks office again".',
        '"Call the parks office again" is done.',
        'Notes on "Call the parks office again": Booked 11 AM to 4 PM',
        'Changed what "Pay the deposit" depends on.',
    ]


def test_reviewed_answers_are_compacted_but_all_answers_and_wording_remain(tmp_path):
    store = GoalStore(tmp_path)
    goal = store.create('chat', 'Goal', 'assistant')
    claim_wake(store, goal)
    question = GoalQuestionChange(id='q', question='Which plan?')
    goal = change_question(store, goal.id, question)
    for index in range(8):
        store.save_answers('chat', GoalAnswerSubmission(goal_id=goal.id, answers=[{
            'question_id': 'q', 'question_revision': goal.questions[0].revision, 'answer': f'Plan {index}',
        }]))
        goal = change_question(store, goal.id, question)
    assert len(goal.questions[0].answers) == goal.questions[0].reviewed_answer_count == 2
    assert goal.questions[0].revision == 1
    goal = change_question(store, goal.id, GoalQuestionChange(id='q', status='resolved'))
    assert not goal.questions
    answers = [entry for entry in pages(store, goal.id) if entry['kind'] == 'answer']
    assert len(answers) == 8 and answers[-1]['data']['answer'] == 'Plan 0'
    assert all(entry['actor'] == 'user' and entry['claim_id'] is None for entry in answers)
    goal = change_question(store, goal.id, GoalQuestionChange(id='q', status='open'))
    assert goal.questions[0].revision == 3
    assert goal.questions[0].question == 'Which plan?'


@pytest.mark.parametrize('failed_file', ['history', 'goal.json'])
def test_failed_save_keeps_previous_state_and_history_visible(tmp_path, monkeypatch, failed_file):
    store = GoalStore(tmp_path)
    goal = store.create('chat', 'Goal', 'assistant')
    before = store.read_history(goal.id)
    original = store._files._write_json

    def fail(path, data):
        if path.name == failed_file or path.parent.name == failed_file:
            raise OSError('simulated disk failure')
        original(path, data)

    monkeypatch.setattr(store._files, '_write_json', fail)
    with pytest.raises(OSError, match='disk failure'):
        save_summary(store, goal.id, 'Should roll back')
    restored = GoalStore(tmp_path)
    assert restored.get(goal.id) == goal
    assert restored.read_history(goal.id) == before
    save_summary(restored, goal.id, 'Retry succeeds')
    assert restored.read_history(goal.id, 'Should roll back')['entries'] == []
    assert len(restored.read_history(goal.id, 'Retry succeeds')['entries']) == 1


def test_deleting_conversation_removes_its_journal_and_questions_only(tmp_path):
    store = GoalStore(tmp_path)
    goal = store.create('chat', 'Goal', 'assistant')
    claim_wake(store, goal)
    ask(store, goal)
    save_summary(store, goal.id, 'Checked options')
    other = store.create('other-chat', 'Keep me', 'assistant')
    store.delete_for_conversation('chat')
    assert store.get(goal.id) is None
    assert store.get(other.id) is not None
    assert store.read_history(other.id)['entries']
    assert not (tmp_path / goal.id).exists()
    assert (tmp_path / other.id / 'goal.json').exists()


def test_goal_files_are_readable_and_current_reads_do_not_load_history(tmp_path, monkeypatch):
    store = GoalStore(tmp_path)
    goal = store.create('chat', 'Grow the neighborhood newsletter', 'assistant')
    save_summary(store, goal.id, 'Library confirmed our announcement')
    directory = tmp_path / goal.id
    state = json.loads((directory / 'goal.json').read_text())
    assert state['objective'] == goal.objective
    assert state['summary'] == 'Library confirmed our announcement'
    batches = [json.loads(path.read_text()) for path in sorted((directory / 'history').glob('*.json'))]
    assert batches[-1]['entries'][-1]['data']['after']['summary'] == 'Library confirmed our announcement'

    def reject_history(*args):
        raise AssertionError('Current goal reads must not load history')

    monkeypatch.setattr(store._files, '_batches', reject_history)
    assert store.get(goal.id).summary == 'Library confirmed our announcement'
    assert store.list()[0].id == goal.id


def test_unpublished_question_update_is_invisible_after_restart(tmp_path, monkeypatch):
    store = GoalStore(tmp_path)
    goal = store.create('chat', 'Plan an event', 'assistant')
    claim_wake(store, goal)
    ask(store, goal, question_id='time', text='Which afternoon?')
    original = store._files._write_json

    def fail(path, data):
        if path.name == 'goal.json':
            raise OSError('snapshot unavailable')
        original(path, data)

    monkeypatch.setattr(store._files, '_write_json', fail)
    with pytest.raises(OSError):
        change_question(store, goal.id, GoalQuestionChange(id='time', status='resolved'))
    monkeypatch.undo()
    restored = GoalStore(tmp_path)
    assert restored.question(goal.id, 'time').status == 'open'
    assert not any(entry['data'].get('status') == 'resolved' for entry in pages(restored, goal.id))
    change_question(restored, goal.id, GoalQuestionChange(id='time', status='withdrawn'))
    assert restored.question(goal.id, 'time').status == 'withdrawn'
