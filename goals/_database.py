"""Transactional current state and an append-only, searchable goal journal."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from ._models import Goal, GoalQuestion

PAGE_SIZE = 20


class GoalDatabase:
    """Keep history out of the frequently read and rewritten working snapshot."""

    def __init__(self, base: Path) -> None:
        base.mkdir(parents=True, exist_ok=True)
        self.path = base / 'goals.sqlite3'
        with closing(self.connect()) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS goals (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, state TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS goals_conversation ON goals(conversation_id, created_at);
                CREATE TABLE IF NOT EXISTS questions (
                    goal_id TEXT NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
                    id TEXT NOT NULL, state TEXT NOT NULL, PRIMARY KEY(goal_id, id)
                );
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal_id TEXT NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL, created_at TEXT NOT NULL,
                    summary TEXT NOT NULL, data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS history_goal ON history(goal_id, id DESC);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY);
            ''')
            # Real migration consumer: goals saved by the experimental JSON store.
            # One transaction imports all records; originals remain as recovery copies.
            if not db.execute("SELECT 1 FROM metadata WHERE key='json_imported'").fetchone():
                for source in sorted(base.glob('*.json')):
                    raw = json.loads(source.read_text(encoding='utf-8'))
                    if source.stem != raw['id'] or not re.fullmatch(r'[a-f0-9]{32}', source.stem):
                        raise ValueError(f'Invalid legacy goal file: {source.name}')
                    versions = []
                    for question in raw.get('questions', []):
                        versions.extend(question.pop('history', []))
                    goal = Goal.model_validate(raw)
                    goal = self._save(db, goal, 'Imported saved goal')
                    for version in versions:
                        self._event(db, goal, 'question', version['question'], version, version['updated_at'])
                    rows = db.execute('SELECT kind,created_at,summary,data FROM history WHERE goal_id=? ORDER BY created_at,id', (goal.id,)).fetchall()
                    db.execute('DELETE FROM history WHERE goal_id=?', (goal.id,))
                    wording = {(version['id'], version['revision']): version['question'] for version in versions}
                    for row in rows:
                        kind, created_at, summary, data = row
                        if kind == 'answer':
                            answer = json.loads(data)
                            summary = wording.get((answer['question_id'], answer['question_revision']), summary)
                            answer['question'] = summary
                            data = json.dumps(answer, ensure_ascii=False)
                        db.execute('INSERT INTO history(goal_id,kind,created_at,summary,data) VALUES (?,?,?,?,?)',
                                   (goal.id, kind, created_at, summary, data))
                    db.execute('UPDATE goals SET state=? WHERE id=?', (goal.model_dump_json(), goal.id))
                db.execute("INSERT INTO metadata VALUES ('json_imported')")

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    @staticmethod
    def _event(
        db: sqlite3.Connection, goal: Goal, kind: str, summary: str,
        data: dict[str, Any], created_at: str | None = None,
    ) -> None:
        db.execute('INSERT INTO history(goal_id,kind,created_at,summary,data) VALUES (?,?,?,?,?)',
                   (goal.id, kind, created_at or goal.updated_at, summary, json.dumps(data, ensure_ascii=False)))
        goal.history_count += 1

    def save(self, goal: Goal, reason: str) -> Goal:
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            return self._save(db, goal, reason)

    def _save(self, db: sqlite3.Connection, goal: Goal, reason: str) -> Goal:
        goal = Goal.model_validate(goal.model_dump())
        row = db.execute('SELECT state FROM goals WHERE id=?', (goal.id,)).fetchone()
        previous = Goal.model_validate_json(row['state']) if row else None
        goal.history_count = previous.history_count if previous else 0
        # Parent row exists before inserting journal/question rows. The transaction
        # commits the compact snapshot and every related event together.
        db.execute('INSERT OR IGNORE INTO goals VALUES (?,?,?,?)',
                   (goal.id, goal.conversation_id, goal.created_at, goal.model_dump_json()))
        if previous is None:
            self._event(db, goal, 'goal', reason or 'Goal assigned', {
                'objective': goal.objective, 'kind': goal.kind, 'constraints': goal.constraints,
                'success_criteria': goal.success_criteria, 'status': goal.status,
                'outcome': goal.outcome, 'next_action': goal.next_action,
            }, goal.created_at)
        groups = {
            'plan': ['plan'], 'summary': ['summary'], 'facts': ['known_facts'],
            'goal': ['objective', 'kind', 'constraints', 'success_criteria', 'profile_id'],
            'state': ['status', 'resume_at', 'wake_reason', 'status_reason', 'outcome', 'next_action'],
        }
        for kind, fields in groups.items():
            after = {key: getattr(goal, key) for key in fields}
            before = {key: getattr(previous, key) for key in fields} if previous else {}
            if after != before and (previous or kind in {'plan', 'summary', 'facts'}):
                if not previous and not any(after.values()):
                    continue
                data = json.loads(json.dumps({'before': before, 'after': after}, default=lambda obj: obj.model_dump()))
                label = reason or (goal.status_reason if kind == 'state' else '') or f'{kind.capitalize()} updated'
                self._event(db, goal, kind, label, data)
        old_progress = {item.id for item in previous.progress} if previous else set()
        new_progress = [item for item in goal.progress if item.id not in old_progress]
        for item in new_progress:
            self._event(db, goal, 'progress', item.summary, item.model_dump(), item.created_at)
        goal.progress_count = (previous.progress_count if previous else 0) + len(new_progress)
        goal.progress = goal.progress[-20:]
        for question in goal.questions:
            row = db.execute('SELECT state FROM questions WHERE goal_id=? AND id=?', (goal.id, question.id)).fetchone()
            old = GoalQuestion.model_validate_json(row['state']) if row else None
            if old is None or question.revision != old.revision:
                self._event(db, goal, 'question', question.question, question.model_dump(exclude={'answers'}), question.updated_at)
            for answer in question.answers[len(old.answers) if old else 0:]:
                self._event(db, goal, 'answer', question.question, {
                    'question': question.question, **answer.model_dump(),
                }, answer.created_at)
            # Retain pending answers and two reviewed answers in the working view.
            drop = max(0, question.reviewed_answer_count - 2)
            question.answers = question.answers[drop:]
            question.reviewed_answer_count -= drop
            db.execute('INSERT INTO questions VALUES (?,?,?) ON CONFLICT(goal_id,id) DO UPDATE SET state=excluded.state',
                       (goal.id, question.id, question.model_dump_json()))
        goal.questions = [question for question in goal.questions if question.status == 'open']
        db.execute('UPDATE goals SET state=? WHERE id=?', (goal.model_dump_json(), goal.id))
        return goal

    def get(self, goal_id: str) -> Goal | None:
        with closing(self.connect()) as db:
            row = db.execute('SELECT state FROM goals WHERE id=?', (goal_id,)).fetchone()
            return Goal.model_validate_json(row['state']) if row else None

    def list(self) -> list[Goal]:
        with closing(self.connect()) as db:
            return [Goal.model_validate_json(row['state']) for row in db.execute('SELECT state FROM goals ORDER BY created_at DESC')]

    def question(self, goal_id: str, question_id: str) -> GoalQuestion | None:
        with closing(self.connect()) as db:
            row = db.execute('SELECT state FROM questions WHERE goal_id=? AND id=?', (goal_id, question_id)).fetchone()
            return GoalQuestion.model_validate_json(row['state']) if row else None

    def read_history(self, goal_id: str, query: str, before: int | None) -> dict:
        if before is not None and before < 1:
            raise ValueError('History cursor must be positive')
        if len(query) > 1000:
            raise ValueError('Search text must be at most 1000 characters')
        with closing(self.connect()) as db:
            rows = db.execute('''SELECT id, kind, created_at, summary, data FROM history
                WHERE goal_id=? AND (? IS NULL OR id < ?)
                AND (?='' OR instr(lower(summary || ' ' || data), lower(?)) > 0)
                ORDER BY id DESC LIMIT ?''', (goal_id, before, before, query, query, PAGE_SIZE + 1)).fetchall()
            entries = [{**dict(row), 'data': json.loads(row['data'])} for row in rows[:PAGE_SIZE]]
            return {'entries': entries, 'next_before': entries[-1]['id'] if len(rows) > PAGE_SIZE else None}

    def delete_for_conversation(self, conversation_id: str) -> None:
        with closing(self.connect()) as db, db:
            ids = [row[0] for row in db.execute('SELECT id FROM goals WHERE conversation_id=?', (conversation_id,))]
            db.execute('DELETE FROM goals WHERE conversation_id=?', (conversation_id,))
        for goal_id in ids:
            (self.path.parent / f'{goal_id}.json').unlink(missing_ok=True)
