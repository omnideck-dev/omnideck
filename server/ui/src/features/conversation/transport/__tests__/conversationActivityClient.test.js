import { describe, expect, it } from 'vitest';
import { decodeActivityMessage } from '../conversationActivityClient.js';

describe('activity message boundary', () => {
    it.each(['snapshot', 'started', 'finished'])('accepts %s messages', (type) => {
        const message = { type, runs: [{ conversation_id: 'chat', run_id: 'run' }] };
        expect(decodeActivityMessage(JSON.stringify(message))).toEqual(message);
    });

    it.each([
        'not json', 'null', '[]', '{}',
        '{"type":"unknown","runs":[]}',
        '{"type":"snapshot","runs":null}',
        '{"type":"snapshot","runs":[null]}',
        '{"type":"started","runs":[{"conversation_id":"chat","run_id":3}]}',
        '{"type":"finished","runs":[{"conversation_id":"","run_id":"run"}]}',
    ])('rejects invalid payload %s', (payload) => {
        expect(() => decodeActivityMessage(payload)).toThrow();
    });
});
