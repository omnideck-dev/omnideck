import { act, render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AgentProvider, useAgentDispatch, useAgentState } from '../AgentState.jsx';

function renderWithProvider() {
    let dispatch;
    let state;

    function Inspector() {
        state = useAgentState();
        dispatch = useAgentDispatch();
        return null;
    }

    render(
        <AgentProvider>
            <Inspector />
        </AgentProvider>,
    );
    return {
        getState: () => state,
        dispatch: (action) => act(() => dispatch(action)),
    };
}

function agentStarted(agentId, { name = 'root', parentAgentId = null } = {}) {
    return {
        type: 'AGENT_STARTED',
        agentId,
        agentName: name,
        parentAgentId,
        instruction: '',
        timestamp: Date.now(),
    };
}

describe('agent state', () => {
    describe('finalized agent iterations', () => {
        const finalIteration = {
            type: 'FINALIZE_AGENT_ITERATION',
            agentId: 'root-1',
            thinking: 'final reasoning',
            content: 'final answer',
            toolCalls: [{ name: 'shell', arguments: { cmd: 'pwd' } }],
            timestamp: 1234,
        };

        const expectedActivity = [
            { type: 'thinking', thinking: 'final reasoning', timestamp: 1234 },
            { type: 'content', content: 'final answer', timestamp: 1234 },
            {
                type: 'tool_call',
                name: 'shell',
                arguments: { cmd: 'pwd' },
                timestamp: 1234,
            },
        ];

        it('replaces temporary streamed text with the finalized iteration', () => {
            const { getState, dispatch } = renderWithProvider();
            dispatch(agentStarted('root-1'));
            dispatch({
                type: 'APPEND_STREAM_CHUNK',
                agentId: 'root-1',
                thinking: 'partial reasoning',
                content: 'partial answer',
            });
            dispatch(finalIteration);

            expect(getState().agents['root-1'].activityLog).toEqual(expectedActivity);
            expect(getState().agents['root-1'].inflightActivityStart).toBeNull();
        });

        it('appends the same finalized iteration during restore', () => {
            const { getState, dispatch } = renderWithProvider();
            dispatch(agentStarted('root-1'));
            dispatch(finalIteration);
            expect(getState().agents['root-1'].activityLog).toEqual(expectedActivity);
        });
    });

    it('carries root context usage into the next turn until a new value arrives', () => {
        const { getState, dispatch } = renderWithProvider();
        const first = {
            context_used: 12000,
            context_limit: 200000,
            fill_ratio: 0.06,
            compaction_threshold: 0.75,
        };
        const second = { ...first, context_used: 30000, fill_ratio: 0.15 };

        dispatch(agentStarted('root-1'));
        dispatch({
            type: 'UPDATE_ITERATION',
            agentId: 'root-1',
            iteration: 4,
            maxIterations: 40,
            contextUsage: first,
        });
        dispatch(agentStarted('root-2'));
        expect(getState().agents['root-2'].contextUsage).toEqual(first);

        dispatch({
            type: 'UPDATE_ITERATION',
            agentId: 'root-2',
            iteration: 1,
            maxIterations: 40,
            contextUsage: second,
        });
        expect(getState().agents['root-2'].contextUsage).toEqual(second);
    });

    it('builds the agent graph for sub-agents', () => {
        const { getState, dispatch } = renderWithProvider();
        dispatch(agentStarted('root-1'));
        dispatch(agentStarted('child-1', { name: 'researcher', parentAgentId: 'root-1' }));

        expect(getState().rootId).toBe('root-1');
        expect(getState().agents['root-1'].childIds).toEqual(['child-1']);
        expect(getState().agents['child-1'].parentId).toBe('root-1');
    });

    it('follows a new root without resetting network history', () => {
        const { getState, dispatch } = renderWithProvider();
        dispatch(agentStarted('root-1'));
        dispatch(agentStarted('child-1', { parentAgentId: 'root-1' }));
        dispatch(agentStarted('root-2'));

        expect(getState().rootId).toBe('root-2');
        expect(getState().agents['root-1'].childIds).toEqual(['child-1']);
    });

    it('records persisted completion time and status', () => {
        const { getState, dispatch } = renderWithProvider();
        const timestamp = Date.parse('2026-06-01T16:28:03+00:00');
        dispatch(agentStarted('root-1'));
        dispatch({
            type: 'AGENT_COMPLETED',
            agentId: 'root-1',
            status: 'success',
            timestamp,
        });

        expect(getState().agents['root-1']).toMatchObject({
            status: 'success',
            completedAt: timestamp,
        });
    });

    it('resets all agent state', () => {
        const { getState, dispatch } = renderWithProvider();
        dispatch(agentStarted('root-1'));
        dispatch(agentStarted('child-1', { parentAgentId: 'root-1' }));
        dispatch({ type: 'RESET' });

        expect(getState()).toEqual({
            agents: {},
            rootId: null,
        });
    });
});
