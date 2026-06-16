import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ChatPanel from '../ChatPanel.jsx';

// The message list and composer pull in streaming/profile machinery that
// isn't relevant to the title bar — stub them out.
vi.mock('../ChatMessages.jsx', () => ({ default: () => <div data-testid="chat-messages" /> }));
vi.mock('../ChatInput.jsx', () => ({ default: () => <div data-testid="chat-input" /> }));

// ChatPanel reads the root agent from the agent-state context; drive it here.
const { agentState } = vi.hoisted(() => ({ agentState: { value: { rootId: null, agents: {} } } }));
vi.mock('../../hooks/useAgentState.jsx', () => ({ useAgentState: () => agentState.value }));

beforeEach(() => { agentState.value = { rootId: null, agents: {} }; });

const userMsg = (id) => ({ id, role: 'user', content: 'hi' });
const agentMsg = (id) => ({ id, role: 'assistant', content: 'hello' });

function renderPanel(props = {}) {
    render(
        <ChatPanel
            messages={[]}
            onSend={vi.fn()}
            onStop={vi.fn()}
            isStreaming={false}
            {...props}
        />,
    );
}

describe('ChatPanel title bar', () => {
    it('falls back to "Chat" when there is no root agent', () => {
        renderPanel();
        expect(screen.getByTestId('chat-title')).toHaveTextContent('Chat');
    });

    it('shows the agent name as the title when a root agent exists', () => {
        agentState.value = { rootId: 'r', agents: { r: { name: 'Omnideck' } } };
        renderPanel();
        expect(screen.getByTestId('chat-title')).toHaveTextContent('Omnideck');
    });

    it('hides the turn count for an empty conversation', () => {
        renderPanel();
        expect(screen.queryByTestId('chat-turns')).not.toBeInTheDocument();
    });

    it('counts a turn per user message', () => {
        renderPanel({ messages: [userMsg('a'), agentMsg('b'), userMsg('c'), agentMsg('d')] });
        expect(screen.getByTestId('chat-turns')).toHaveTextContent('2 turns');
    });

    it('uses the singular for a single turn', () => {
        renderPanel({ messages: [userMsg('a'), agentMsg('b')] });
        expect(screen.getByTestId('chat-turns')).toHaveTextContent('1 turn');
    });

    it('shows the network indicator only once the network is activated', () => {
        renderPanel({ networkActivated: false });
        expect(screen.queryByTestId('network-indicator')).not.toBeInTheDocument();
        render(
            <ChatPanel messages={[]} onSend={vi.fn()} onStop={vi.fn()} isStreaming={false}
                networkActivated networkAgentCount={3} networkRunningCount={1} onOpenNetwork={vi.fn()} />,
        );
        expect(screen.getByTestId('network-indicator')).toHaveTextContent('3 agents');
    });
});
