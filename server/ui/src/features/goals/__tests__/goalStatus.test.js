import { describe, expect, it } from 'vitest';
import { formatRunTime, goalNeedsAnswer, goalStatus, nextUpStep, reasonLine } from '../goalStatus.js';

const NOW = Date.parse('2026-11-11T15:00:00Z');
const FUTURE = '2026-11-14T15:00:00Z';
const PAST = '2026-11-10T15:00:00Z';

const question = (id, fields = {}) => ({ id, question: `Question ${id}`, choices: [], status: 'open', revision: 1, answers: [], reviewed_answer_count: 0, ...fields });
const goal = (fields = {}) => ({
    id: 'g1', objective: 'Book the pavilion', paused: false, running: false, note: '',
    next: { kind: 'wait', question_ids: [] }, questions: [], plan: [], ...fields,
});
const wake = (at, reason = 'planned') => ({ kind: 'wake', id: 'w1', at, reason });

describe('goalStatus', () => {
    // One row per line of the requirements table, plus the error row, in table order.
    it.each([
        ['Done', goal({ next: { kind: 'done', outcome: 'Booked' } }), 'done', 'Done', 'bi-check-circle', 'success'],
        ['Cancelled', goal({ next: { kind: 'cancelled' } }), 'cancelled', 'Cancelled', 'bi-x-circle', 'neutral'],
        ['Paused', goal({ paused: true, next: wake(FUTURE) }), 'paused', 'Paused', 'bi-pause-circle', 'neutral'],
        ['Working', goal({ running: true, next: wake(PAST) }), 'working', 'Working', 'bi-arrow-repeat', 'accent'],
        ['Stopped by an error', goal({ next: { kind: 'error', message: 'Rate limit reached (429).' } }), 'error', 'Stopped by an error', 'bi-exclamation-triangle', 'danger'],
        ['N questions for you', goal({ next: { kind: 'wait', question_ids: ['a', 'b'] }, questions: [question('a'), question('b')] }), 'questions', '2 questions for you', 'bi-chat-left-text', 'warning'],
        ['Waiting for you', goal({ next: { kind: 'wait', question_ids: [] } }), 'waiting', 'Waiting for you', 'bi-chat-left-text', 'warning'],
        ['Resumes at a time', goal({ next: wake(FUTURE) }), 'scheduled', `Resumes ${formatRunTime(FUTURE)}`, 'bi-clock', 'neutral'],
        ['Starting', goal({ next: wake(PAST) }), 'starting', 'Starting', 'bi-play-circle', 'accent'],
    ])('derives %s', (_name, input, key, label, icon, tone) => {
        expect(goalStatus(input, NOW)).toMatchObject({ key, label, icon, tone, extraQuestions: 0 });
    });

    it.each([
        ['done over paused', goal({ paused: true, next: { kind: 'done', outcome: 'Booked' } }), 'done'],
        ['cancelled over running', goal({ running: true, next: { kind: 'cancelled' } }), 'cancelled'],
        ['paused over running', goal({ paused: true, running: true, next: wake(PAST) }), 'paused'],
        ['paused over error', goal({ paused: true, next: { kind: 'error', message: 'Failed' } }), 'paused'],
        ['working over error', goal({ running: true, next: { kind: 'error', message: 'Failed' } }), 'working'],
        ['working over waiting', goal({ running: true, next: { kind: 'wait', question_ids: [] } }), 'working'],
    ])('checks the table in order: %s', (_name, input, key) => {
        expect(goalStatus(input, NOW).key).toBe(key);
    });

    it('returns null without a goal', () => {
        expect(goalStatus(null, NOW)).toBeNull();
    });

    it('adds the count of questions that do not block work to the label', () => {
        const status = goalStatus(goal({ next: wake(FUTURE), questions: [question('day')] }), NOW);
        expect(status).toMatchObject({ key: 'scheduled', extraQuestions: 1, label: `Resumes ${formatRunTime(FUTURE)} · 1 question` });
        expect(status.shortLabel).toBe(formatRunTime(FUTURE));
    });

    it('counts non-blocking questions on paused and working goals too', () => {
        expect(goalStatus(goal({ paused: true, questions: [question('a'), question('b')] }), NOW).label).toBe('Paused · 2 questions');
        expect(goalStatus(goal({ running: true, next: wake(PAST), questions: [question('a')] }), NOW).label).toBe('Working · 1 question');
    });

    it('counts only blocking questions the user has not answered yet', () => {
        const answered = question('a', { answers: [{ answer: 'Tuesday', question_revision: 1 }] });
        const reviewed = question('b', { answers: [{ answer: 'No', question_revision: 1 }], reviewed_answer_count: 1 });
        const status = goalStatus(goal({ next: { kind: 'wait', question_ids: ['a', 'b'] }, questions: [answered, reviewed] }), NOW);
        expect(status).toMatchObject({ key: 'questions', label: '1 question for you', shortLabel: '1 question' });
    });

    it('treats a wait whose blocking questions are all answered as waiting', () => {
        const answered = question('a', { answers: [{ answer: 'Tuesday', question_revision: 1 }] });
        expect(goalStatus(goal({ next: { kind: 'wait', question_ids: ['a'] }, questions: [answered] }), NOW).key).toBe('waiting');
    });

    it('does not count questions on ended goals', () => {
        expect(goalStatus(goal({ next: { kind: 'done', outcome: 'Booked' }, questions: [question('a')] }), NOW).label).toBe('Done');
    });

    it('uses short labels for narrow rows', () => {
        expect(goalStatus(goal({ next: { kind: 'error', message: 'x' } }), NOW).shortLabel).toBe('Error');
        expect(goalStatus(goal(), NOW).shortLabel).toBe('Waiting');
    });
});

describe('goalNeedsAnswer', () => {
    it('is false for a future wake with an open question', () => {
        expect(goalNeedsAnswer(goal({ next: wake(FUTURE), questions: [question('a')] }))).toBe(false);
    });

    it('is true for a wait, with or without questions', () => {
        expect(goalNeedsAnswer(goal({ next: { kind: 'wait', question_ids: ['a'] }, questions: [question('a')] }))).toBe(true);
        expect(goalNeedsAnswer(goal({ next: { kind: 'wait', question_ids: [] } }))).toBe(true);
    });

    it('is true for an error', () => {
        expect(goalNeedsAnswer(goal({ next: { kind: 'error', message: 'Failed' } }))).toBe(true);
    });

    it('is false for a paused wait', () => {
        expect(goalNeedsAnswer(goal({ paused: true, next: { kind: 'wait', question_ids: ['a'] }, questions: [question('a')] }))).toBe(false);
    });

    it('is false while a run is going, and for ended goals', () => {
        expect(goalNeedsAnswer(goal({ running: true }))).toBe(false);
        expect(goalNeedsAnswer(goal({ next: { kind: 'done', outcome: 'Booked' } }))).toBe(false);
        expect(goalNeedsAnswer(goal({ next: { kind: 'cancelled' } }))).toBe(false);
        expect(goalNeedsAnswer(undefined)).toBe(false);
    });
});

describe('reasonLine', () => {
    it('shows the agent note for waiting on questions, working, starting and scheduled goals', () => {
        const note = 'Called the parks office. Booked 11 AM to 4 PM.';
        expect(reasonLine(goal({ note, next: { kind: 'wait', question_ids: ['a'] }, questions: [question('a')] }), NOW)).toBe(note);
        expect(reasonLine(goal({ note, running: true, next: wake(PAST) }), NOW)).toBe(note);
        expect(reasonLine(goal({ note, next: wake(PAST) }), NOW)).toBe(note);
        expect(reasonLine(goal({ note, next: wake(FUTURE) }), NOW)).toBe(note);
    });

    it('shows no line when there is no note yet', () => {
        expect(reasonLine(goal({ next: wake(FUTURE) }), NOW)).toBe('');
    });

    it('explains a wait with no questions', () => {
        expect(reasonLine(goal({ note: 'Old note' }), NOW)).toBe('The agent stopped without choosing what to do next.');
    });

    it('shows no line for error, done and cancelled goals', () => {
        expect(reasonLine(goal({ note: 'n', next: { kind: 'error', message: 'Failed' } }), NOW)).toBe('');
        expect(reasonLine(goal({ note: 'n', next: { kind: 'done', outcome: 'Booked' } }), NOW)).toBe('');
        expect(reasonLine(goal({ note: 'n', next: { kind: 'cancelled' } }), NOW)).toBe('');
    });

    it('says when Resume will run a paused goal', () => {
        expect(reasonLine(goal({ paused: true, note: 'n', next: wake(FUTURE) }), NOW))
            .toBe(`When you resume, it runs ${formatRunTime(FUTURE)} as planned.`);
        expect(reasonLine(goal({ paused: true, next: wake(PAST) }), NOW))
            .toBe(`When you resume, it runs right away. It was set for ${formatRunTime(PAST)}.`);
        expect(reasonLine(goal({ paused: true, next: wake(FUTURE, 'interrupted') }), NOW))
            .toBe('When you resume, it runs right away.');
    });
});

describe('nextUpStep', () => {
    it('shows the next step only when a run is coming', () => {
        const fields = { next_step: 'Book the pavilion' };
        expect(nextUpStep(goal({ ...fields, next: wake(FUTURE) }))).toBe('Book the pavilion');
        expect(nextUpStep(goal({ ...fields, paused: true, next: wake(FUTURE) }))).toBe('Book the pavilion');
        expect(nextUpStep(goal({ ...fields, next: { kind: 'wait', question_ids: [] } }))).toBe('');
        expect(nextUpStep(goal({ ...fields, next: { kind: 'error', message: 'Failed' } }))).toBe('');
        expect(nextUpStep(goal({ ...fields, next: { kind: 'done', outcome: 'Booked' } }))).toBe('');
        expect(nextUpStep(goal({ ...fields, next: { kind: 'cancelled' } }))).toBe('');
        expect(nextUpStep(goal({ next: wake(FUTURE), next_step: '' }))).toBe('');
    });
});
