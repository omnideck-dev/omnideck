import { describe, expect, it } from 'vitest';
import { getConversationEventActions } from '../conversationEventActions.js';

describe('getConversationEventActions', () => {
    it('assembles the actions for every state owner', () => {
        const event = {
            id: 'event-1',
            type: 'agent_started',
            agent_id: 'root-1',
            agent_name: 'omnideck',
            parent_agent_id: null,
            depth: 0,
            timestamp: '2026-01-01T00:00:00Z',
        };

        const actions = getConversationEventActions(event);
        expect(actions.session).toEqual([
            { type: 'RETAIN_EVENT', event },
            { type: 'SET_ROOT_AGENT', agentId: 'root-1' },
        ]);
        expect(actions.agent.immediate).toEqual([expect.objectContaining({
            type: 'AGENT_STARTED',
            agentId: 'root-1',
        })]);
        expect(actions.agent.ordered).toEqual([]);
        expect(actions.workspace).toEqual([{
            type: 'WORKSPACE_AGENT_STARTED',
            agentId: 'root-1',
            parentAgentId: null,
        }]);
    });

    it('returns an empty plan for missing events', () => {
        expect(getConversationEventActions(null)).toEqual({
            session: [],
            agent: { immediate: [], ordered: [] },
            workspace: [],
        });
    });
});
