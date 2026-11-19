import { describe, expect, it } from 'vitest';

import { activityEffect, decodeActivityMessage } from '../activityStream.js';
import { APP_EFFECT_TYPES } from '../appEffectTypes.js';

const goal = { id: 'g1', conversation_id: 'chat', revision: 2, next: { kind: 'wait', question_ids: [] } };

describe('activity message boundary', () => {
    it.each(['run_snapshot', 'run_started', 'run_finished'])('accepts %s messages', (type) => {
        const message = { type, runs: [{ conversation_id: 'chat', run_id: 'run' }] };
        expect(decodeActivityMessage(JSON.stringify(message))).toEqual(message);
    });

    it('accepts goal messages', () => {
        expect(decodeActivityMessage(JSON.stringify({ type: 'goal_snapshot', goals: [goal] }))).toEqual({ type: 'goal_snapshot', goals: [goal] });
        const changed = { type: 'goal_changed', conversation_id: 'chat', goal };
        expect(decodeActivityMessage(JSON.stringify(changed))).toEqual(changed);
    });

    it.each([
        'not json', 'null', '[]', '{}',
        '{"type":"unknown","runs":[]}',
        '{"type":"snapshot","runs":[]}',
        '{"type":"run_snapshot","runs":null}',
        '{"type":"run_snapshot","runs":[null]}',
        '{"type":"run_started","runs":[{"conversation_id":"chat","run_id":3}]}',
        '{"type":"run_finished","runs":[{"conversation_id":"","run_id":"run"}]}',
        '{"type":"goal_snapshot","goals":null}',
        '{"type":"goal_changed","conversation_id":"chat","goal":{"id":"g1"}}',
    ])('drops invalid or unknown message %s', (payload) => {
        expect(() => decodeActivityMessage(payload)).toThrow();
    });
});

describe('activity effects', () => {
    it('dispatches each message as its named effect with a camelCase payload', () => {
        const runs = [{ conversation_id: 'chat', run_id: 'run' }];
        const camel = { runs: [{ conversationId: 'chat', runId: 'run' }] };
        expect(activityEffect({ type: 'run_snapshot', runs })).toEqual({ type: APP_EFFECT_TYPES.RUNS_SNAPSHOT, payload: camel });
        expect(activityEffect({ type: 'run_started', runs })).toEqual({ type: APP_EFFECT_TYPES.RUNS_STARTED, payload: camel });
        expect(activityEffect({ type: 'run_finished', runs })).toEqual({ type: APP_EFFECT_TYPES.RUNS_FINISHED, payload: camel });
        expect(activityEffect({ type: 'goal_snapshot', goals: [goal] })).toEqual({ type: APP_EFFECT_TYPES.GOALS_SNAPSHOT, payload: { goals: [goal] } });
        expect(activityEffect({ type: 'goal_changed', conversation_id: 'chat', goal })).toEqual({
            type: APP_EFFECT_TYPES.GOALS_CHANGED, payload: { conversationId: 'chat', goal },
        });
    });
});
