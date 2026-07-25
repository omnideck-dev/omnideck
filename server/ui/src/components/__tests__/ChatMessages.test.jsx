import { useEffect } from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { AgentProvider, useAgentDispatch } from '../../features/agent/AgentState.jsx';
import ChatMessages from '../ChatMessages.jsx';

function Harness({ turns }) {
    const dispatch = useAgentDispatch();
    useEffect(() => {
        dispatch({
            type: 'AGENT_STARTED',
            agentId: 'root-1',
            agentName: 'omnideck',
            parentAgentId: null,
            instruction: '',
            timestamp: 1,
        });
    }, [dispatch]);
    return <ChatMessages turns={turns} stalled />;
}

describe('ChatMessages live status', () => {
    it('shows live status only on the latest turn when root identity is reused', () => {
        const turns = [
            {
                id: 'turn-1',
                agentId: 'root-1',
                children: [
                    {
                        kind: 'user_prompt',
                        id: 'user-1',
                        content: 'First question',
                    },
                    {
                        kind: 'iteration',
                        id: 'iteration-1',
                        content: 'First answer',
                        thinking: '',
                        toolCalls: [],
                    },
                ],
            },
            {
                id: 'turn-2',
                agentId: 'root-1',
                children: [
                    {
                        kind: 'user_prompt',
                        id: 'user-2',
                        content: 'Latest question',
                    },
                ],
            },
        ];

        render(
            <AgentProvider>
                <Harness turns={turns} />
            </AgentProvider>,
        );

        expect(screen.getAllByTestId('ephemeral-status')).toHaveLength(1);
        expect(screen.getByTestId('ephemeral-status')).toHaveTextContent(
            'Thinking…',
        );
        expect(screen.queryByText('Working…')).not.toBeInTheDocument();
    });
});
