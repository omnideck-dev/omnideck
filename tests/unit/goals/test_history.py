"""Long-running goal recall, bounded state and atomic journal writes."""

import json
import sqlite3

import pytest

from goals import GoalAnswerSubmission, GoalQuestionChange, GoalStep, GoalStore


def pages(store, goal_id, query=''):
    entries, cursor = [], None
    while True:
        page = store.read_history(goal_id, query, cursor)
        entries.extend(page['entries'])
        cursor = page['next_before']
        if cursor is None:
            return entries


def test_long_history_stays_retrievable_without_growing_working_state(tmp_path):
    store = GoalStore(tmp_path)
    goal = store.create('chat', 'Grow website traffic', 'assistant', kind='ongoing')
    for index in range(1000):
        goal = store.record_progress(goal.id, f'Campaign {index}: result {index}', 'Review results')
    assert goal.progress_count == 1000 and len(goal.progress) == 20
    assert len(goal.model_dump_json()) < 10000
    restored = GoalStore(tmp_path).get(goal.id)
    assert restored.progress_count == 1000
    entries = pages(store, goal.id, 'Campaign')
    assert len(entries) == len({entry['id'] for entry in entries}) == 1000
    assert entries[-1]['summary'] == 'Campaign 0: result 0'
    assert store.read_history(goal.id, 'Campaign 17:')['entries'][0]['summary'] == 'Campaign 17: result 17'
    assert store.read_history(goal.id, '%')['entries'] == []  # literal search, not SQL wildcard


def test_history_cursor_is_stable_when_new_entries_arrive(tmp_path):
    store = GoalStore(tmp_path)
    goal = store.create('chat', 'Goal', 'assistant')
    for index in range(40):
        store.record_progress(goal.id, f'Entry {index}')
    first = store.read_history(goal.id, 'Entry')
    store.record_progress(goal.id, 'Entry arriving during pagination')
    second = store.read_history(goal.id, 'Entry', first['next_before'])
    ids = [entry['id'] for entry in first['entries'] + second['entries']]
    assert len(ids) == len(set(ids)) == 40
    assert second['next_before'] is None


def test_plan_revisions_and_summary_preserve_decisions_and_superseded_state(tmp_path):
    store = GoalStore(tmp_path)
    goal = store.create('chat', 'Goal', 'assistant')
    goal = store.update(goal.id, goal.revision, plan=[GoalStep(id='ads', title='Try paid ads')], reason='Test demand')
    goal = store.update(goal.id, goal.revision, plan=[GoalStep(id='referrals', title='Ask for referrals')], reason='Ads cost too much')
    goal = store.update(goal.id, goal.revision, summary='Paid ads failed. Try referrals next.')
    goal = store.update(goal.id, goal.revision, summary='Referrals are working. Expand the program.')
    entry = store.read_history(goal.id, 'Ads cost too much')['entries'][0]
    assert entry['data']['before']['plan'][0]['id'] == 'ads'
    assert entry['data']['after']['plan'][0]['id'] == 'referrals'
    assert 'Paid ads failed' in json.dumps(store.read_history(goal.id, 'Paid ads failed'))
    assert goal.summary == 'Referrals are working. Expand the program.'


def test_reviewed_answers_are_compacted_but_all_answers_and_wording_remain(tmp_path):
    store = GoalStore(tmp_path)
    goal = store.create('chat', 'Goal', 'assistant')
    goal = store.claim(goal.id, goal.wake_id, 'claim')
    question = GoalQuestionChange(id='q', question='Which plan?', status='open')
    goal = store.update_questions(goal.id, [question], '', goal.revision, claim_id='claim')
    for index in range(8):
        store.submit_answers('chat', GoalAnswerSubmission(goal_id=goal.id, answers=[{
            'question_id': 'q', 'question_revision': goal.questions[0].revision, 'answer': f'Plan {index}',
        }]))
        goal = store.get(goal.id)
        goal = store.update_questions(goal.id, [question], f'Current: plan {index}', goal.revision, claim_id='claim')
    assert len(goal.questions[0].answers) == goal.questions[0].reviewed_answer_count == 2
    goal = store.update_questions(goal.id, [question.model_copy(update={'status': 'resolved'})], 'Current: plan 7', goal.revision, claim_id='claim')
    assert not goal.questions
    answers = [entry for entry in pages(store, goal.id) if entry['kind'] == 'answer']
    assert len(answers) == 8 and answers[-1]['data']['answer'] == 'Plan 0'
    goal = store.update_questions(goal.id, [question], 'Current: plan 7', goal.revision, claim_id='claim')
    assert goal.questions[0].revision == 11


def test_failed_journal_write_rolls_back_state_and_events(tmp_path, monkeypatch):
    store = GoalStore(tmp_path)
    goal = store.create('chat', 'Goal', 'assistant')
    before = store.read_history(goal.id)
    original = store._db._event

    def fail(db, *args, **kwargs):
        original(db, *args, **kwargs)
        raise RuntimeError('simulated disk failure')

    monkeypatch.setattr(store._db, '_event', fail)
    with pytest.raises(RuntimeError, match='disk failure'):
        store.record_progress(goal.id, 'Should roll back')
    assert store.get(goal.id) == goal
    assert store.read_history(goal.id) == before


def test_deleting_conversation_removes_its_journal_and_questions_only(tmp_path):
    store = GoalStore(tmp_path)
    goal = store.create('chat', 'Goal', 'assistant')
    goal = store.claim(goal.id, goal.wake_id, 'claim')
    store.update_questions(goal.id, [GoalQuestionChange(id='q', question='Which plan?', status='open')], '', goal.revision, claim_id='claim')
    store.record_progress(goal.id, 'Checked options')
    other = store.create('other-chat', 'Keep me', 'assistant')
    store.delete_for_conversation('chat')
    assert store.get(goal.id) is None
    assert store.get(other.id) is not None
    assert store.read_history(other.id)['entries']
    with sqlite3.connect(tmp_path / 'goals.sqlite3') as db:
        assert db.execute('SELECT count(*) FROM questions WHERE goal_id=?', (goal.id,)).fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM history WHERE goal_id=?', (goal.id,)).fetchone()[0] == 0
