import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ChatPanel from '../ChatPanel.jsx';

// The message list and composer pull in streaming/profile machinery that
// isn't relevant to the title bar — stub them out.
vi.mock('../ChatMessages.jsx', () => ({ default: () => <div data-testid="chat-messages" /> }));
vi.mock('../ChatInput.jsx', () => ({ default: () => <div data-testid="chat-input" /> }));

// ChatPanel reads the root agent from the agent-state context; drive it here.
const { agentState } = vi.hoisted(() => ({ agentState: { value: { rootId: null, agents: {} } } }));
vi.mock('../../features/agent/AgentState.jsx', () => ({ useAgentState: () => agentState.value }));

beforeEach(() => { agentState.value = { rootId: null, agents: {} }; localStorage.clear(); });

const _turn = (id) => ({ id, agentId: 'root.test.1', children: [] });

function renderPanel(props = {}) {
    render(
        <ChatPanel
            turns={[]}
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

    it('counts a turn per turn object', () => {
        renderPanel({ turns: [_turn('t0'), _turn('t1')] });
        expect(screen.queryByTestId('chat-turns')).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Details' }));
        fireEvent.click(screen.getByText('Advanced'));
        expect(screen.getByTestId('chat-turns')).toHaveTextContent('2');
    });

    it('uses the singular for a single turn', () => {
        renderPanel({ turns: [_turn('t0')] });
        fireEvent.click(screen.getByRole('button', { name: 'Details' }));
        fireEvent.click(screen.getByText('Advanced'));
        expect(screen.getByTestId('chat-turns')).toHaveTextContent('1');
    });

    it('shows the network indicator only when the conversation has an agent network', () => {
        agentState.value = { rootId: 'root', agents: {
            root: { id: 'root', parentId: null, name: 'Primary' },
            child: { id: 'child', parentId: 'root', name: 'Analyst', status: 'running' },
        } };
        const onOpenNetwork = vi.fn();
        renderPanel({ onOpenNetwork });
        expect(screen.queryByTestId('network-indicator')).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: /Details/ }));
        expect(screen.getByTestId('network-indicator')).toHaveTextContent('Agents 1');
        fireEvent.click(screen.getByTestId('network-indicator'));
        expect(onOpenNetwork).toHaveBeenCalledOnce();
    });

    it('delegates conversation artifact navigation to the desktop', () => {
        const onOpenArtifacts = vi.fn();
        renderPanel({ onOpenArtifacts });

        fireEvent.click(screen.getByRole('button', { name: /Details/ }));
        fireEvent.click(screen.getByTestId('conversation-artifacts-trigger'));
        expect(onOpenArtifacts).toHaveBeenCalledOnce();
    });
});
