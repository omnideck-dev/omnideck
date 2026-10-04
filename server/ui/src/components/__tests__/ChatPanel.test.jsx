import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ChatPanel from '../ChatPanel.jsx';

// The message list and composer pull in streaming/profile machinery that
// isn't relevant to the title bar — stub them out.
vi.mock('../ChatMessages.jsx', () => ({ default: () => <div data-testid="chat-messages" /> }));
const inputProps = vi.hoisted(() => ({ current: null }));
vi.mock('../ChatInput.jsx', () => ({ default: (props) => {
    inputProps.current = props;
    return <input data-testid="chat-input" aria-label="Draft" />;
} }));

// ChatPanel reads the root agent from the agent-state context; drive it here.
const { agentState } = vi.hoisted(() => ({ agentState: { value: { rootId: null, agents: {} } } }));
vi.mock('../../features/agent/AgentState.jsx', () => ({ useAgentState: () => agentState.value }));

beforeEach(() => { agentState.value = { rootId: null, agents: {} }; });

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
    it('passes the shared goal dialog callback to the composer', () => {
        const onRequestGoal = vi.fn();
        renderPanel({ onRequestGoal });
        expect(inputProps.current.onRequestGoal).toBe(onRequestGoal);
    });
    it('removes goal UI cleanly across feature toggles without remounting the composer', () => {
        const props = { turns: [], onSend: vi.fn(), onStop: vi.fn(), isStreaming: false, conversationId: 'chat-1' };
        const view = render(<ChatPanel {...props} goalPanel={<section key="chat-1" data-testid="goal-panel">Waiting</section>} />);
        const composer = screen.getByTestId('chat-input');
        fireEvent.change(composer, { target: { value: 'My unsent question' } });
        view.rerender(<ChatPanel {...props} goalPanel={null} />);
        expect(screen.queryByTestId('goal-panel')).not.toBeInTheDocument();
        view.rerender(<ChatPanel {...props} goalPanel={<section key="chat-1" data-testid="goal-panel">Paused</section>} />);
        expect(screen.getAllByTestId('goal-panel')).toHaveLength(1);
        expect(screen.getByTestId('goal-panel')).toHaveTextContent('Paused');
        expect(screen.getByTestId('chat-input')).toBe(composer);
        expect(composer).toHaveValue('My unsent question');
    });
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
        expect(screen.getByTestId('chat-turns')).toHaveTextContent('2 turns');
    });

    it('uses the singular for a single turn', () => {
        renderPanel({ turns: [_turn('t0')] });
        expect(screen.getByTestId('chat-turns')).toHaveTextContent('1 turn');
    });

    it('shows the network indicator only when the conversation has an agent network', () => {
        renderPanel({ networkAgentCount: 0 });
        expect(screen.queryByTestId('network-indicator')).not.toBeInTheDocument();
        render(
            <ChatPanel turns={[]} onSend={vi.fn()} onStop={vi.fn()} isStreaming={false}
                networkAgentCount={3} networkRunningCount={1} onOpenNetwork={vi.fn()} />,
        );
        expect(screen.getByTestId('network-indicator')).toHaveTextContent('3 agents');
    });

    it('delegates conversation artifact navigation to the desktop', () => {
        const onOpenArtifacts = vi.fn();
        renderPanel({ onOpenArtifacts });

        fireEvent.click(screen.getByTestId('conversation-artifacts-trigger'));
        expect(onOpenArtifacts).toHaveBeenCalledOnce();
    });
});
