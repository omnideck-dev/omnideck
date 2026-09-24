import { useEffect } from 'react';
import {
    fireEvent,
    render,
    screen,
} from '@testing-library/react';
import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from 'vitest';

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

describe('ChatMessages jump to latest', () => {
    function renderScrollableChat() {
        render(
            <AgentProvider>
                <Harness turns={[]} />
            </AgentProvider>,
        );

        const messages = document.getElementById('chatMessages');
        Object.defineProperties(messages, {
            scrollHeight: { configurable: true, value: 1000 },
            clientHeight: { configurable: true, value: 400 },
        });
        // Far enough from the bottom for the existing auto-scroll logic to
        // recognize that the reader intentionally moved upward.
        messages.scrollTop = 200;
        fireEvent.scroll(messages);
        return messages;
    }

    it('appears away from the bottom and jumps to the latest message', () => {
        const messages = renderScrollableChat();
        const jumpButton = screen.getByRole('button', {
            name: 'Jump to latest message',
        });

        expect(jumpButton).toHaveAttribute('aria-keyshortcuts', 'Alt+End');
        fireEvent.click(jumpButton);

        expect(messages.scrollTop).toBe(1000);
        expect(screen.queryByTestId('jump-to-latest')).not.toBeInTheDocument();
    });

    it('supports Alt+End while the control is visible', () => {
        const messages = renderScrollableChat();

        fireEvent.keyDown(document, { key: 'End', altKey: true });

        expect(messages.scrollTop).toBe(1000);
        expect(screen.queryByTestId('jump-to-latest')).not.toBeInTheDocument();
    });
});

describe('ChatMessages auto-follow', () => {
    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('follows late content resizing until the reader scrolls away', () => {
        let resizeCallback;
        const disconnect = vi.fn();
        vi.stubGlobal('ResizeObserver', class ResizeObserver {
            constructor(callback) {
                resizeCallback = callback;
            }

            observe() {}

            disconnect() {
                disconnect();
            }
        });

        render(
            <AgentProvider>
                <Harness turns={[]} />
            </AgentProvider>,
        );

        const messages = document.getElementById('chatMessages');
        let scrollHeight = 1000;
        Object.defineProperties(messages, {
            scrollHeight: {
                configurable: true,
                get: () => scrollHeight,
            },
            clientHeight: { configurable: true, value: 400 },
        });

        messages.scrollTop = 600;
        fireEvent.scroll(messages);
        scrollHeight = 1200;
        resizeCallback();
        expect(messages.scrollTop).toBe(1200);

        messages.scrollTop = 200;
        fireEvent.scroll(messages);
        scrollHeight = 1400;
        resizeCallback();
        expect(messages.scrollTop).toBe(200);
    });
});
