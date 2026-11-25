import { afterEach, describe, expect, it, vi } from 'vitest';

import { activityEffect, decodeActivityMessage, subscribeActivityStream } from '../activityStream.js';
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

    it('accepts chat list messages', () => {
        const conversation = { conversation_id: 'chat', title: 'Reunion', first_message: '', started_at: '', turn_count: 1, pinned: false, folder_id: null };
        const messages = [
            { type: 'conversation_resync' },
            { type: 'conversation_changed', conversation, archived: false },
            { type: 'conversation_removed', conversation_id: 'chat' },
        ];
        for (const message of messages) {
            expect(decodeActivityMessage(JSON.stringify(message))).toEqual(message);
        }
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
        '{"type":"conversation_changed","conversation":{"conversation_id":""},"archived":false}',
        '{"type":"conversation_changed","conversation":{"conversation_id":"chat"}}',
        '{"type":"conversation_removed","conversation_id":7}',
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
        const conversation = { conversation_id: 'chat', title: 'Reunion', first_message: '', started_at: '', turn_count: 1, pinned: false, folder_id: null };
        expect(activityEffect({ type: 'conversation_resync' })).toEqual({ type: APP_EFFECT_TYPES.CONVERSATIONS_RESYNC, payload: null });
        expect(activityEffect({ type: 'conversation_changed', conversation, archived: true })).toEqual({
            type: APP_EFFECT_TYPES.CONVERSATIONS_CHANGED, payload: { conversation, archived: true },
        });
        expect(activityEffect({ type: 'conversation_removed', conversation_id: 'chat' })).toEqual({
            type: APP_EFFECT_TYPES.CONVERSATIONS_REMOVED, payload: { conversationId: 'chat' },
        });
    });
});

class FakeEventSource {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSED = 2;
    static opened = [];

    constructor(url) {
        this.url = url;
        this.readyState = FakeEventSource.OPEN;
        FakeEventSource.opened.push(this);
    }

    close() {
        this.readyState = FakeEventSource.CLOSED;
    }
}

function setVisibility(state) {
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state });
    document.dispatchEvent(new Event('visibilitychange'));
}

describe('activity stream connection', () => {
    afterEach(() => {
        FakeEventSource.opened = [];
        vi.unstubAllGlobals();
        setVisibility('visible');
    });

    it('opens a new connection when the page comes back after the old one closed', () => {
        vi.stubGlobal('EventSource', FakeEventSource);
        const stop = subscribeActivityStream(vi.fn());
        FakeEventSource.opened[0].readyState = FakeEventSource.CLOSED;

        setVisibility('hidden');
        expect(FakeEventSource.opened).toHaveLength(1);
        setVisibility('visible');

        expect(FakeEventSource.opened).toHaveLength(2);
        expect(FakeEventSource.opened[1].url).toBe('/api/chat/activity');
        stop();
        expect(FakeEventSource.opened[1].readyState).toBe(FakeEventSource.CLOSED);
    });

    it('keeps a live connection when the page comes back', () => {
        vi.stubGlobal('EventSource', FakeEventSource);
        const stop = subscribeActivityStream(vi.fn());

        setVisibility('visible');
        window.dispatchEvent(new Event('online'));

        expect(FakeEventSource.opened).toHaveLength(1);
        stop();
    });

    it('opens a new connection when the browser comes back online after the old one closed', () => {
        vi.stubGlobal('EventSource', FakeEventSource);
        const stop = subscribeActivityStream(vi.fn());
        FakeEventSource.opened[0].readyState = FakeEventSource.CLOSED;

        window.dispatchEvent(new Event('online'));

        expect(FakeEventSource.opened).toHaveLength(2);
        stop();
    });
});
