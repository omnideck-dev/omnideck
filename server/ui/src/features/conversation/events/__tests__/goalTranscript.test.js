import { describe, expect, it } from 'vitest';
import { addDayHeaders, goalDividerItem, isShownGoalEvent } from '../goalTranscript.js';

const divider = (id, transition, timestamp = '2026-10-23T09:00:00') => ({
    kind: 'goal_transition', id, transition, step: '', questionCount: 0, timestamp, resumeAt: null,
});
const reply = (id) => ({ kind: 'iteration', id, iterationIndex: 0, content: id, thinking: '', toolCalls: [] });
const prompt = (id, timestamp = '2026-10-23T09:00:00') => ({
    kind: 'user_prompt', id, content: id, attachments: [], context: [], isNudge: false, timestamp,
});
const turn = (id, children) => ({ id, agentId: `root.${id}`, children });
const ids = (turns) => turns.map((item) => item.children.map((child) => child.id));

describe('goalDividerItem', () => {
    const event = (data) => ({ id: 'evt', type: 'goal', timestamp: '2026-10-23T09:00:00', goal_id: 'g', data });

    it('makes a run divider from a wakeup and an outcome divider from each outcome kind', () => {
        expect(goalDividerItem(event({ kind: 'wakeup', wake_id: 'w', reason: 'planned', step: 'Book it' })))
            .toMatchObject({ transition: 'run', step: 'Book it' });
        for (const kind of ['scheduled', 'waiting', 'error', 'completed']) {
            expect(goalDividerItem(event({ kind, resume_at: null, question_count: 1 }))).toMatchObject({ transition: kind });
        }
    });

    it('shows nothing for edited, state_notice, an unknown kind and an old paused divider', () => {
        for (const kind of ['edited', 'state_notice', 'mystery', 'paused', 'started']) {
            expect(goalDividerItem(event({ kind }))).toBeNull();
            expect(isShownGoalEvent(event({ kind }))).toBe(false);
        }
    });
});

describe('addDayHeaders', () => {
    it('adds a header before the first message or divider of each day', () => {
        const turns = [
            turn('t0', [divider('started', 'started', '2026-10-23T09:00:00'), prompt('ask', '2026-10-23T09:05:00')]),
            turn('t1', [divider('run', 'run', '2026-10-24T09:00:00'), reply('r')]),
        ];
        expect(ids(addDayHeaders(turns))).toEqual([['day_started', 'started', 'ask'], ['day_run', 'run', 'r']]);
    });

    it('adds nothing to a chat without a goal', () => {
        const turns = [turn('t0', [prompt('hi', '2026-10-23T09:00:00')]), turn('t1', [prompt('again', '2026-10-24T09:00:00')])];
        expect(addDayHeaders(turns)).toBe(turns);
    });
});
