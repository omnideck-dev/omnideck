import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AgentProvider, useAgentDispatch } from '../AgentState.jsx';
import useAgentNetworkCounts from '../useAgentNetworkCounts.js';

function useHarness() {
    return {
        counts: useAgentNetworkCounts(),
        dispatch: useAgentDispatch(),
    };
}

function wrapper({ children }) {
    return <AgentProvider>{children}</AgentProvider>;
}

function startAgent(dispatch, agentId, parentAgentId = null) {
    dispatch({
        type: 'AGENT_STARTED',
        agentId,
        agentName: agentId,
        parentAgentId,
        instruction: '',
        timestamp: Date.now(),
    });
}

describe('useAgentNetworkCounts', () => {
    it('derives network availability and status counts from agent trees', () => {
        const { result } = renderHook(useHarness, { wrapper });

        act(() => startAgent(result.current.dispatch, 'single-root'));
        expect(result.current.counts).toEqual({
            total: 0,
            running: 0,
            complete: 0,
            error: 0,
        });

        act(() => {
            startAgent(result.current.dispatch, 'network-root');
            startAgent(result.current.dispatch, 'child', 'network-root');
            result.current.dispatch({
                type: 'AGENT_COMPLETED',
                agentId: 'child',
                status: 'success',
                timestamp: Date.now(),
            });
        });

        expect(result.current.counts).toEqual({
            total: 2,
            running: 1,
            complete: 1,
            error: 0,
        });
    });
});
