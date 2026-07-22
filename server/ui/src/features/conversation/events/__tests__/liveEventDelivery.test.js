import { describe, expect, it, vi } from 'vitest';
import { createLiveEventDelivery } from '../liveEventDelivery.js';

function event(type, fields = {}) {
    return {
        id: `event-${type}`,
        type,
        agent_id: 'root-1',
        depth: 0,
        timestamp: '2026-07-22T12:00:00.000Z',
        ...fields,
    };
}

function frameScheduler() {
    let callback = null;
    return {
        requestFrame: vi.fn((next) => {
            callback = next;
            return 42;
        }),
        cancelFrame: vi.fn(),
        run: () => callback?.(),
    };
}

describe('createLiveEventDelivery', () => {
    it('applies lifecycle actions immediately and batches ordered activity', () => {
        const frame = frameScheduler();
        const onAgentAction = vi.fn();
        const delivery = createLiveEventDelivery({
            onAgentAction,
            requestFrame: frame.requestFrame,
            cancelFrame: frame.cancelFrame,
        });

        delivery.deliver(event('agent_started', { agent_name: 'General' }));
        delivery.deliver(event('content', { content: 'root output' }));
        delivery.deliver(event('content', {
            agent_id: 'child-1', depth: 1, content: 'child output',
        }));

        expect(onAgentAction).toHaveBeenCalledTimes(1);
        expect(onAgentAction).toHaveBeenLastCalledWith(expect.objectContaining({
            type: 'AGENT_STARTED', agentId: 'root-1',
        }));
        expect(frame.requestFrame).toHaveBeenCalledTimes(1);

        frame.run();

        expect(onAgentAction.mock.calls.slice(1).map(([action]) => ({
            type: action.type,
            agentId: action.agentId,
            content: action.content,
        }))).toEqual([
            { type: 'APPEND_STREAM_CHUNK', agentId: 'root-1', content: 'root output' },
            { type: 'APPEND_STREAM_CHUNK', agentId: 'child-1', content: 'child output' },
        ]);
    });

    it('flushes queued activity before finishing a turn', () => {
        const frame = frameScheduler();
        const order = [];
        const delivery = createLiveEventDelivery({
            onAgentAction: () => order.push('agent activity'),
            onSessionAction: (action) => {
                if (action.type === 'FINISH_TURN') order.push('turn finished');
            },
            requestFrame: frame.requestFrame,
            cancelFrame: frame.cancelFrame,
        });

        delivery.deliver(event('content', { content: 'last output' }));
        delivery.deliver(event('turn_end'));

        expect(frame.cancelFrame).toHaveBeenCalledWith(42);
        expect(order).toEqual(['agent activity', 'turn finished']);
    });

    it('keeps workspace and one-time callback failures from stopping delivery', () => {
        const onToolCreated = vi.fn();
        const delivery = createLiveEventDelivery({
            onWorkspaceAction: vi.fn(() => { throw new Error('preview failed'); }),
            oneTimeActions: { onToolCreated },
            requestFrame: vi.fn(),
            cancelFrame: vi.fn(),
        });

        expect(() => delivery.deliver(event('browser_screenshot', {
            url: 'https://example.test', screenshot: 'image',
        }))).not.toThrow();
        delivery.deliver(event('tool_created'));

        expect(onToolCreated).toHaveBeenCalledTimes(1);
    });
});
