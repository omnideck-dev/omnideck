import { describe, expect, it, vi } from 'vitest';
import { handleSessionEvent } from '../sessionEventHandler.js';

function event(type, fields = {}) {
    return {
        id: `event-${type}`,
        type,
        agent_id: 'agent-1',
        depth: 0,
        ...fields,
    };
}

function actions() {
    return {
        retainEvent: vi.fn(),
        confirmUserMessage: vi.fn(),
        finalizeIteration: vi.fn(),
        updateInProgressIteration: vi.fn(),
        setRootAgent: vi.fn(),
        finishTurn: vi.fn(),
    };
}

describe('handleSessionEvent', () => {
    it('retains transcript records and confirms user input', () => {
        const session = actions();
        const userMessage = event('user_message', { content: 'hello' });

        handleSessionEvent(userMessage, session);

        expect(session.retainEvent).toHaveBeenCalledWith(userMessage);
        expect(session.confirmUserMessage).toHaveBeenCalledTimes(1);
    });

    it('tracks in-progress output and finalizes iterations', () => {
        const session = actions();
        const content = event('content', { content: 'partial' });
        const iteration = event('iteration', { content: 'complete' });

        handleSessionEvent(content, session);
        expect(session.updateInProgressIteration).toHaveBeenCalledWith(content);
        expect(session.retainEvent).not.toHaveBeenCalled();

        handleSessionEvent(iteration, session);
        expect(session.retainEvent).toHaveBeenCalledWith(iteration);
        expect(session.finalizeIteration).toHaveBeenCalledTimes(1);
    });

    it('sets only root agents on the open session', () => {
        const session = actions();
        const root = event('agent_started', { parent_agent_id: null });
        const child = event('agent_started', { depth: 1, parent_agent_id: 'agent-1' });

        handleSessionEvent(root, session);
        handleSessionEvent(child, session);

        expect(session.setRootAgent).toHaveBeenCalledTimes(1);
        expect(session.setRootAgent).toHaveBeenCalledWith(root);
        expect(session.retainEvent).toHaveBeenCalledTimes(2);
    });

    it('finishes turns without retaining the boundary signal', () => {
        const session = actions();

        handleSessionEvent(event('turn_end'), session);

        expect(session.finishTurn).toHaveBeenCalledTimes(1);
        expect(session.retainEvent).not.toHaveBeenCalled();
    });

    it('does not retain one-time or workspace-only events', () => {
        const session = actions();

        handleSessionEvent(event('tool_created'), session);
        handleSessionEvent(event('browser_screenshot'), session);
        handleSessionEvent(null, session);

        for (const action of Object.values(session)) {
            expect(action).not.toHaveBeenCalled();
        }
    });
});
