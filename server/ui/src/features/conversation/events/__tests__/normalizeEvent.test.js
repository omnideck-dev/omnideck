import { describe, expect, it } from 'vitest';
import { normalizeLiveEvent } from '../normalizeEvent.js';

describe('normalizeLiveEvent', () => {
    it('returns null for missing payload', () => {
        expect(normalizeLiveEvent(null)).toBeNull();
        expect(normalizeLiveEvent(undefined)).toBeNull();
        expect(normalizeLiveEvent({})).toBeNull();
        expect(normalizeLiveEvent({ payload: null })).toBeNull();
    });

    it('normalizes an iteration stream envelope into canonical event shape', () => {
        const envelope = {
            id: 'evt_abc',
            timestamp: '2026-05-31T12:00:00',
            conversation_id: 'c1',
            agent_id: 'root.test.1',
            agent_name: 'TEST',
            depth: 0,
            payload: {
                type: 'iteration',
                iteration_index: 2,
                content: 'response text',
                thinking: 'reasoning',
                tool_calls: [{ id: 'tc1', name: 'shell' }],
            },
        };
        const out = normalizeLiveEvent(envelope);
        expect(out).toMatchObject({
            id: 'evt_abc',
            type: 'iteration',
            timestamp: '2026-05-31T12:00:00',
            conversation_id: 'c1',
            agent_id: 'root.test.1',
            agent_name: 'TEST',
            depth: 0,
            iteration_index: 2,
            content: 'response text',
            thinking: 'reasoning',
            tool_calls: [{ id: 'tc1', name: 'shell' }],
        });
    });

    it('mints an id when the stream envelope has no id', () => {
        const sse = {
            timestamp: '2026-05-31T12:00:00',
            payload: { type: 'agent_started', agent_id: 'root.test.1' },
        };
        const out = normalizeLiveEvent(sse);
        expect(out.id).toMatch(/^live_/);
    });

    it('synthesizes timestamp when missing', () => {
        const sse = { payload: { type: 'agent_completed' } };
        const out = normalizeLiveEvent(sse);
        expect(out.timestamp).toBeTypeOf('string');
        expect(out.timestamp.length).toBeGreaterThan(0);
    });

    it('preserves envelope fields under their own keys, not under payload', () => {
        const sse = {
            id: 'evt_x', agent_id: 'a1', agent_name: 'A1', depth: 0,
            conversation_id: 'c1', timestamp: '2026-01-01',
            payload: { type: 'tool_result', tool_call_id: 'tc1', tool_name: 'shell', content: 'ok' },
        };
        const out = normalizeLiveEvent(sse);
        expect(out.tool_call_id).toBe('tc1');
        expect(out.tool_name).toBe('shell');
        expect(out.agent_id).toBe('a1');
        // Should not have a nested `type` from payload — top-level type only.
        expect(out.type).toBe('tool_result');
    });

    it('handles user_message events with attachments + is_nudge', () => {
        const sse = {
            id: 'evt_um', agent_id: 'a1', timestamp: '2026-01-01',
            payload: {
                type: 'user_message',
                content: 'do the thing',
                attachments: [{ filename: 'x.txt', content_type: 'text/plain', path: '/tmp/x.txt' }],
                is_nudge: true,
            },
        };
        const out = normalizeLiveEvent(sse);
        expect(out.content).toBe('do the thing');
        expect(out.attachments).toHaveLength(1);
        expect(out.is_nudge).toBe(true);
    });
});
