import { describe, expect, it, vi } from 'vitest';
import { applyConversationEvent } from '../applyConversationEvent.js';

describe('applyConversationEvent', () => {
    it('gives the same canonical event to each state handler', () => {
        const event = { id: 'event-1', type: 'agent_started' };
        const handlers = {
            session: vi.fn(),
            agent: vi.fn(),
            workspace: vi.fn(),
        };

        expect(applyConversationEvent(event, handlers)).toEqual([]);

        expect(handlers.session).toHaveBeenCalledWith(event);
        expect(handlers.agent).toHaveBeenCalledWith(event);
        expect(handlers.workspace).toHaveBeenCalledWith(event);
    });

    it('isolates one handler failure from the other handlers', () => {
        const error = new Error('session unavailable');
        const handlers = {
            session: vi.fn(() => { throw error; }),
            agent: vi.fn(),
            workspace: vi.fn(),
        };

        expect(applyConversationEvent({ type: 'content' }, handlers)).toEqual([
            { handlerName: 'session', error },
        ]);
        expect(handlers.agent).toHaveBeenCalledTimes(1);
        expect(handlers.workspace).toHaveBeenCalledTimes(1);
    });

    it('ignores missing events and handlers', () => {
        expect(applyConversationEvent(null)).toEqual([]);
        expect(applyConversationEvent({ type: 'content' })).toEqual([]);
    });
});
