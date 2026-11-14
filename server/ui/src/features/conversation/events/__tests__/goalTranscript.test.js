import { describe, expect, it } from 'vitest';
import { addDayHeaders, hideRunAfterStart, placeRunOutcomes } from '../goalTranscript.js';

// Small hand-made turns. Each pass is tested on its own.
const divider = (id, transition, timestamp = '2026-10-23T09:00:00') => ({
    kind: 'goal_transition', id, transition, objective: '', step: '', questionCount: 0, timestamp, resumeAt: null,
});
const reply = (id) => ({ kind: 'iteration', id, iterationIndex: 0, content: id, thinking: '', toolCalls: [] });
const prompt = (id, timestamp = '2026-10-23T09:00:00') => ({
    kind: 'user_prompt', id, content: id, attachments: [], context: [], isNudge: false, timestamp,
});
const turn = (id, children, finished = true) => ({ id, agentId: `root.${id}`, finished, children });
const ids = (turns) => turns.map((item) => item.children.map((child) => child.id));

describe('hideRunAfterStart', () => {
    it('hides the run divider right after the start divider, across turns', () => {
        const turns = [turn('t0', [prompt('ask'), divider('started', 'started')]), turn('t1', [divider('run', 'run'), reply('r')])];
        expect(ids(hideRunAfterStart(turns))).toEqual([['ask', 'started'], ['r']]);
    });

    it('keeps a run divider that follows anything else', () => {
        const turns = [
            turn('t0', [divider('started', 'started'), reply('r0')]),
            turn('t1', [divider('run', 'run'), reply('r1')]),
            turn('t2', [divider('resumed', 'resumed'), divider('run2', 'run')]),
        ];
        expect(ids(hideRunAfterStart(turns))).toEqual([['started', 'r0'], ['run', 'r1'], ['resumed', 'run2']]);
    });
});

describe('placeRunOutcomes', () => {
    it('moves the outcome below the reply the agent wrote after choosing it', () => {
        const turns = [turn('t', [divider('run', 'run'), reply('tools'), divider('done', 'completed'), reply('reply')])];
        expect(ids(placeRunOutcomes(turns))).toEqual([['run', 'tools', 'reply', 'done']]);
    });

    it('shows only the last outcome when the agent changed its mind', () => {
        const turns = [turn('t', [reply('a'), divider('wait', 'waiting'), reply('b'), divider('later', 'scheduled'), reply('c')])];
        expect(ids(placeRunOutcomes(turns))).toEqual([['a', 'b', 'c', 'later']]);
    });

    it('shows no outcome while the run is still going', () => {
        const turns = [turn('t', [reply('a'), divider('done', 'completed'), reply('streaming')], false)];
        expect(ids(placeRunOutcomes(turns))).toEqual([['a', 'streaming']]);
    });

    it('shows the outcome of an unfinished turn once a later turn exists', () => {
        const turns = [turn('t0', [reply('a'), divider('later', 'scheduled'), reply('b')], false), turn('t1', [reply('c')], false)];
        expect(ids(placeRunOutcomes(turns))).toEqual([['a', 'b', 'later'], ['c']]);
    });

    it('keeps a user action after the run below the outcome', () => {
        const turns = [turn('t', [reply('a'), divider('later', 'scheduled'), reply('b'), divider('paused', 'paused')])];
        expect(ids(placeRunOutcomes(turns))).toEqual([['a', 'b', 'later', 'paused']]);
    });

    it('keeps a user action during the run where it happened', () => {
        const turns = [turn('t', [reply('a'), divider('paused', 'paused'), reply('b'), divider('later', 'scheduled')])];
        expect(ids(placeRunOutcomes(turns))).toEqual([['a', 'paused', 'b', 'later']]);
    });

    it('leaves dividers that are not outcomes alone', () => {
        const turns = [turn('t', [divider('run', 'run'), reply('a'), divider('error', 'error'), divider('cancelled', 'cancelled')])];
        expect(ids(placeRunOutcomes(turns))).toEqual([['run', 'a', 'error', 'cancelled']]);
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
