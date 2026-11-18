import { describe, expect, it } from 'vitest';

import { clearQueue, consumeReturned, dropQueued, queueMessage } from '../queueState.js';

const empty = { queue: [], returned: [] };
const message = (id) => ({ id, content: id, context: [] });

describe('queue state', () => {
    it('adds a message once', () => {
        const once = queueMessage(empty, message('a'));
        expect(queueMessage(once, message('a'))).toBe(once);
        expect(once.queue).toEqual([message('a')]);
    });

    it('ignores an unknown id when dropping', () => {
        const state = queueMessage(empty, message('a'));
        expect(dropQueued(state, 'missing', true)).toBe(state);
    });

    it('keeps a returned message for the composer and forgets a read one', () => {
        const state = queueMessage(queueMessage(empty, message('a')), message('b'));
        const returned = dropQueued(state, 'a', true);
        expect(returned).toEqual({ queue: [message('b')], returned: [message('a')] });
        expect(dropQueued(returned, 'b', false)).toEqual({ queue: [], returned: [message('a')] });
        expect(consumeReturned(returned, ['a']).returned).toEqual([]);
    });

    it('clears the queue', () => {
        expect(clearQueue(queueMessage(empty, message('a'))).queue).toEqual([]);
    });
});
