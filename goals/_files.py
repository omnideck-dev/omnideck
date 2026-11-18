"""Readable goal snapshots and immutable history batches, committed by revision.

Each goal lives in its chat's folder. The atomically replaced goal.json is the
commit marker. History files are written first; readers only use revisions
published by that snapshot. A failed save leaves the previous state readable,
and retrying replaces the uncommitted history batch. Like the other application
file stores, one backend process owns the directory.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ._models import Goal, GoalHistoryEntry, GoalStep, HistoryActor, local_time

logger = logging.getLogger(__name__)

ARCHIVE_DIRNAME = '_archived'

_STEP_STATUS_WORDS = {
    'pending': 'is pending', 'in_progress': 'is in progress', 'done': 'is done',
    'blocked': 'is blocked', 'skipped': 'was skipped',
}


def plan_changes(before: list[GoalStep], after: list[GoalStep]) -> list[str]:
    """Describe a plan change as short lines, one per changed step."""
    old = {step.id: step for step in before}
    new = {step.id: step for step in after}
    lines = [f'Removed "{step.title}".' for step in before if step.id not in new]
    for step in after:
        previous = old.get(step.id)
        if previous is None:
            lines.append(f'Added "{step.title}".')
            continue
        if previous.title != step.title:
            lines.append(f'Renamed "{previous.title}" to "{step.title}".')
        if previous.status != step.status:
            lines.append(f'"{step.title}" {_STEP_STATUS_WORDS[step.status]}.')
        if previous.notes != step.notes and step.notes:
            lines.append(f'Notes on "{step.title}": {step.notes}')
        if previous.depends_on != step.depends_on:
            lines.append(f'Changed what "{step.title}" depends on.')
    return lines


def state_sentence(before: Goal, after: Goal) -> str:
    """The app's sentence for a change of what happens next or of the pause."""
    following = after.next
    if after.paused and not before.paused:
        return 'Paused the goal.'
    if following != before.next:
        if following.kind == 'wake':
            if following.reason == 'run_now':
                return 'Started a run now.'
            if following.reason == 'retry':
                return 'Retried the goal.'
            if following.reason == 'interrupted':
                return 'The run was interrupted. It will run again.'
            if datetime.fromisoformat(following.at) <= datetime.fromisoformat(after.updated_at):
                return 'Continued with the next step.'
            return f'Scheduled the next run for {local_time(following.at)}.'
        if following.kind == 'wait':
            if before.ended:
                return 'Reopened the goal.'
            count = len(following.question_ids)
            if not count:
                return 'The agent stopped without choosing what to do next.'
            return f'Waiting for answers to {count} question{"s" if count != 1 else ""}.'
        if following.kind == 'error':
            return 'The run stopped with an error.'
        if following.kind == 'done':
            return 'Completed the goal.'
        return 'Cancelled the goal.'
    return 'Paused the goal.' if after.paused else 'Resumed the goal.'

PAGE_SIZE = 20


class GoalFiles:
    """Keep each goal in its chat's folder, with older history readable on demand."""

    def __init__(self, base: Path) -> None:
        base.mkdir(parents=True, exist_ok=True)
        self.base = base

    def goal_dir(self, conversation_id: str, goal_id: str) -> Path:
        return self.base / conversation_id / 'goals' / goal_id

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        temporary = path.with_suffix('.tmp')
        try:
            with temporary.open('w', encoding='utf-8') as stream:
                json.dump(data, stream, indent=2, ensure_ascii=False)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
            if os.name != 'nt':
                descriptor = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _event(
        entries: list[GoalHistoryEntry], goal: Goal, kind: str, summary: str, data: dict[str, Any],
        *, actor: HistoryActor, claim_id: str | None, created_at: str | None = None,
    ) -> None:
        goal.history_count += 1
        entry: GoalHistoryEntry = {
            'id': goal.history_count, 'kind': kind, 'created_at': created_at or goal.updated_at,
            'summary': summary, 'actor': actor, 'claim_id': claim_id, 'data': data,
        }
        entries.append(entry)

    def save(
        self, goal: Goal, *, actor: HistoryActor, claim_id: str | None = None, reason: str = '',
        noted: bool = False,
    ) -> tuple[Goal, list[GoalHistoryEntry]]:
        """Commit a new revision and journal what changed.

        ``reason`` replaces the app's sentence for a change of what happens next.
        ``noted`` journals the note even when the agent repeated its last one.
        """
        goal = Goal.model_validate(goal.model_dump())
        directory = self.goal_dir(goal.conversation_id, goal.id)
        previous = self.get(goal.conversation_id, goal.id)
        expected = previous.revision + 1 if previous else 1
        if goal.revision != expected:
            raise ValueError(f'Expected goal revision {expected}, received {goal.revision}')
        goal.history_count = previous.history_count if previous else 0
        previous_questions = {question.id: question for question in previous.questions} if previous else {}
        entries: list[GoalHistoryEntry] = []
        if previous is None:
            self._event(entries, goal, 'goal', reason or 'Started the goal.', {
                'objective': goal.objective, 'next': goal.next.model_dump(mode='json'),
            }, created_at=goal.created_at, actor=actor, claim_id=claim_id)
        else:
            if goal.objective != previous.objective:
                self._event(entries, goal, 'goal', 'Changed the objective.', {
                    'before': {'objective': previous.objective}, 'after': {'objective': goal.objective},
                }, actor=actor, claim_id=claim_id)
            if goal.plan != previous.plan:
                self._event(entries, goal, 'plan', 'Updated the plan.', {
                    'changes': plan_changes(previous.plan, goal.plan),
                }, actor=actor, claim_id=claim_id)
            if goal.summary != previous.summary:
                self._event(entries, goal, 'summary', 'Updated what the agent knows.', {
                    'summary': goal.summary,
                }, actor=actor, claim_id=claim_id)
            if goal.note and (noted or goal.note != previous.note):
                self._event(entries, goal, 'note', goal.note, {'note': goal.note}, actor=actor, claim_id=claim_id)
            if goal.next != previous.next or goal.paused != previous.paused:
                before = {'next': previous.next.model_dump(mode='json'), 'paused': previous.paused}
                after = {'next': goal.next.model_dump(mode='json'), 'paused': goal.paused}
                self._event(entries, goal, 'state', reason or state_sentence(previous, goal), {
                    'before': before, 'after': after,
                }, actor=actor, claim_id=claim_id)
        if previous is None and goal.plan:
            self._event(entries, goal, 'plan', 'Updated the plan.', {
                'changes': plan_changes([], goal.plan),
            }, actor=actor, claim_id=claim_id)
        for question in goal.questions:
            old = previous_questions.get(question.id)
            if old is None or question.revision != old.revision:
                self._event(entries, goal, 'question', question.question,
                            question.model_dump(exclude={'answers'}), created_at=question.updated_at, actor=actor, claim_id=claim_id)
            for answer in question.answers[len(old.answers) if old else 0:]:
                self._event(entries, goal, 'answer', question.question, {
                    'question': question.question, **answer.model_dump(),
                }, actor='user', claim_id=None, created_at=answer.created_at)
        if previous is None:
            (directory / 'history').mkdir(parents=True, exist_ok=True)
        self._write_json(directory / 'history' / f'{goal.revision:012d}.json', {
            'revision': goal.revision, 'entries': entries,
        })
        self._write_json(directory / 'goal.json', goal.model_dump(mode='json'))
        return goal, entries

    def get(self, conversation_id: str, goal_id: str) -> Goal | None:
        path = self.goal_dir(conversation_id, goal_id) / 'goal.json'
        return Goal.model_validate_json(path.read_text(encoding='utf-8')) if path.exists() else None

    def save_metadata(self, goal: Goal) -> Goal:
        """Save run bookkeeping, such as the claim, without a new revision or history."""
        self._write_json(self.goal_dir(goal.conversation_id, goal.id) / 'goal.json', goal.model_dump(mode='json'))
        return goal

    @staticmethod
    def _read(paths: Iterable[Path]) -> list[Goal]:
        goals = []
        for path in paths:
            try:
                goals.append(Goal.model_validate_json(path.read_text(encoding='utf-8')))
            except (OSError, ValueError, ValidationError):
                logger.exception('Skipping unreadable goal file %s', path)
        return sorted(goals, key=lambda goal: goal.created_at, reverse=True)

    def active(self) -> list[Goal]:
        """Every goal in an active chat, newest first."""
        return self._read(self._active_paths())

    def all_goals(self) -> list[Goal]:
        """Every goal in an active or archived chat, newest first."""
        return self._read([*self._active_paths(), *self.base.glob(f'{ARCHIVE_DIRNAME}/*/goals/*/goal.json')])

    def _active_paths(self) -> list[Path]:
        return [path for path in self.base.glob('*/goals/*/goal.json') if path.parents[2].name != ARCHIVE_DIRNAME]

    def chat_goals(self, conversation_id: str) -> list[Goal]:
        """One active chat's goals, newest first, reading only that chat's folder."""
        return self._read((self.base / conversation_id / 'goals').glob('*/goal.json'))

    def _batches(self, goal: Goal) -> Iterator[dict]:
        directory = self.goal_dir(goal.conversation_id, goal.id) / 'history'
        for path in sorted(directory.glob('*.json'), reverse=True):
            if int(path.stem) <= goal.revision:
                yield json.loads(path.read_text(encoding='utf-8'))

    def entries(self, goal: Goal, after: int) -> Iterator[GoalHistoryEntry]:
        """Read committed entries newest first."""
        for batch in self._batches(goal):
            for entry in reversed(batch['entries']):
                if entry['id'] <= after:
                    return
                yield entry

    def read_history(self, goal: Goal, query: str, before: int | None) -> dict:
        if before is not None and before < 1:
            raise ValueError('History cursor must be positive')
        if len(query) > 1000:
            raise ValueError('Search text must be at most 1000 characters')
        entries: list[GoalHistoryEntry] = []
        needle = query.casefold()
        for entry in self.entries(goal, 0):
            if before is not None and entry['id'] >= before:
                continue
            searchable = entry['summary'] + ' ' + json.dumps(entry['data'], ensure_ascii=False)
            if needle and needle not in searchable.casefold():
                continue
            entries.append(entry)
            if len(entries) > PAGE_SIZE:
                return {'entries': entries[:PAGE_SIZE], 'next_before': entries[PAGE_SIZE - 1]['id']}
        return {'entries': entries, 'next_before': None}
