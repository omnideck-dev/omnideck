import { describe, expect, it } from 'vitest';
import { mapConversationEventToActions } from '../mapConversationEventToActions.js';

describe('mapConversationEventToActions', () => {
    it('does not retain raw tool results in any UI state owner', () => {
        const event = {
            id: 'result-1',
            type: 'tool_result',
            agent_id: 'root-1',
            depth: 0,
            timestamp: '2026-01-01T00:00:00Z',
            tool_call_id: 'call-1',
            tool_name: 'lookup',
            content: 'Large model-only output',
        };
        for (const depth of [0, 1]) {
            expect(mapConversationEventToActions({ ...event, depth })).toEqual({
                session: [],
                agent: { immediate: [], batched: [] },
                workspace: [],
                effects: [],
            });
        }
    });

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

        const actions = mapConversationEventToActions(event);
        expect(actions.session).toEqual([
            { type: 'RETAIN_EVENT', event },
            { type: 'SET_ROOT_AGENT', agentId: 'root-1' },
        ]);
        expect(actions.agent.immediate).toEqual([expect.objectContaining({
            type: 'AGENT_STARTED',
            agentId: 'root-1',
        })]);
        expect(actions.agent.batched).toEqual([]);
        expect(actions.workspace).toEqual([{
            type: 'WORKSPACE_AGENT_STARTED',
            agentId: 'root-1',
            parentAgentId: null,
        }]);
        expect(actions.effects).toEqual([]);
    });

    it('returns empty actions for missing events', () => {
        expect(mapConversationEventToActions(null)).toEqual({
            session: [],
            agent: { immediate: [], batched: [] },
            workspace: [],
            effects: [],
        });
    });
});
