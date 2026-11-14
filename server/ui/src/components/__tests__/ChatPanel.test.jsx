import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ChatPanel from '../ChatPanel.jsx';
import { formatRunTime } from '../../features/goals/goalStatus.js';

vi.mock('../ChatMessages.jsx', () => ({ default: () => <div data-testid="chat-messages" /> }));

// ChatPanel reads the root agent from the agent-state context; drive it here.
const { agentState } = vi.hoisted(() => ({ agentState: { value: { rootId: null, agents: {} } } }));
vi.mock('../../features/agent/AgentState.jsx', () => ({ useAgentState: () => agentState.value }));

beforeEach(() => { localStorage.clear(); agentState.value = { rootId: null, agents: {} }; });

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

describe('ChatPanel header and composer', () => {
    it('starts goals through the add menu without a standalone Goal toggle', () => {
        const onRequestGoal = vi.fn();
        renderPanel({ onRequestGoal });
        expect(screen.queryByRole('button', { name: 'Goal', exact: true })).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Add to chat' }));
        fireEvent.click(screen.getByRole('menuitem', { name: /Start a goal…/ }));
        expect(onRequestGoal).toHaveBeenCalledOnce();
    });
    it('keeps one header and preserves the composer draft across goal feature toggles', () => {
        const props = { turns: [], onSend: vi.fn(), onStop: vi.fn(), isStreaming: false, conversationId: 'chat-1', onDraftChange: vi.fn() };
        const view = render(<ChatPanel {...props} goal={{ id: 'g1', next: { kind: 'wait', question_ids: [] }, questions: [], plan: [] }} />);
        const composer = screen.getByRole('textbox', { name: 'Message' });
        expect(screen.getByTestId('chat-title-bar')).toHaveTextContent('Goal');
        expect(screen.queryByRole('button', { name: 'Pause goal' })).not.toBeInTheDocument();
        fireEvent.change(composer, { target: { value: 'My unsent question' } });
        view.rerender(<ChatPanel {...props} />);
        expect(screen.queryByTestId('goal-panel')).not.toBeInTheDocument();
        view.rerender(<ChatPanel {...props} goal={{ id: 'g1', next: { kind: 'wait', question_ids: [] }, questions: [], plan: [] }} />);
        expect(screen.getByRole('textbox', { name: 'Message' })).toBe(composer);
        expect(composer).toHaveValue('My unsent question');
    });
    it('opens existing goal details from its header status without starting a new goal', () => {
        const onOpenGoal = vi.fn();
        const onRequestGoal = vi.fn();
        renderPanel({ goal: { id: 'g1', paused: true, next: { kind: 'wait', question_ids: [] }, questions: [], plan: [], objective: 'Plan a trip' }, onOpenGoal, onRequestGoal });
        expect(screen.getByTestId('chat-title-bar')).toHaveTextContent('Paused');
        fireEvent.click(screen.getByRole('button', { name: 'Open goal details' }));
        expect(onOpenGoal).toHaveBeenCalledOnce();
        expect(onRequestGoal).not.toHaveBeenCalled();
        expect(screen.queryByRole('button', { name: 'Pause goal' })).not.toBeInTheDocument();
    });
    it('shows the same status in the header as everywhere else, with a non-blocking question count', () => {
        const at = '2099-11-14T15:00:00Z';
        renderPanel({ goal: { id: 'g1', paused: false, running: false, plan: [],
            next: { kind: 'wake', id: 'w1', at, reason: 'planned' },
            questions: [{ id: 'q1', question: 'Which park?', choices: [], status: 'open', revision: 1, answers: [], reviewed_answer_count: 0 }],
        }, onOpenGoal: vi.fn() });
        const [full] = screen.getAllByTestId('goal-status');
        expect(full).toHaveAttribute('data-status', 'scheduled');
        expect(full).toHaveTextContent(`Resumes ${formatRunTime(at)} · 1 question`);
    });
    it('shows "Stopped by an error" in the header for a failed run', () => {
        renderPanel({ goal: { id: 'g1', paused: false, running: false, plan: [], questions: [],
            next: { kind: 'error', message: 'Rate limit reached (429).' } }, onOpenGoal: vi.fn() });
        expect(screen.getByTestId('chat-title-bar')).toHaveTextContent('Stopped by an error');
        expect(screen.getByTestId('chat-title-bar')).not.toHaveTextContent('Rate limit');
    });
    it('keeps the full working step out of the headline and available on hover', () => {
        const step = 'Search live openings for Senior Director / VP Engineering in Austin, remote OR hybrid; capture companies and application links';
        renderPanel({ goal: { id: 'g1', paused: false, next: { kind: 'wake', id: 'w1', at: '2026-10-01T00:00:00Z', reason: 'planned' }, running: true, questions: [], plan: [
            { id: 'done', title: 'Confirm preferences', status: 'done' },
            { id: 'now', title: step, status: 'in_progress' },
        ] }, onOpenGoal: vi.fn() });
        const headline = screen.getByRole('button', { name: 'Open goal details' });
        expect(headline).toHaveTextContent('Working');
        expect(headline).not.toHaveTextContent(step);
        expect(headline).toHaveAttribute('title', `1 of 2 steps done. Now: ${step}. Open goal details`);
    });
    it('falls back to "Chat" when there is no root agent', () => {
        renderPanel();
        fireEvent.click(screen.getByRole('button', { name: 'Conversation details', exact: true }));
        expect(screen.getByTestId('chat-title')).toHaveTextContent('Chat');
    });

    it('shows the agent name as the title when a root agent exists', () => {
        agentState.value = { rootId: 'r', agents: { r: { name: 'Omnideck' } } };
        renderPanel();
        fireEvent.click(screen.getByRole('button', { name: 'Conversation details', exact: true }));
        expect(screen.getByTestId('chat-title')).toHaveTextContent('Omnideck');
    });

    it('hides the turn count for an empty conversation', () => {
        renderPanel();
        fireEvent.click(screen.getByRole('button', { name: 'Conversation details', exact: true }));
        expect(screen.queryByTestId('chat-turns')).not.toBeInTheDocument();
    });

    it('counts a turn per turn object', () => {
        renderPanel({ turns: [_turn('t0'), _turn('t1')] });
        fireEvent.click(screen.getByRole('button', { name: 'Conversation details', exact: true }));
        expect(screen.getByTestId('chat-turns')).toHaveTextContent('2 turns');
    });

    it('uses the singular for a single turn', () => {
        renderPanel({ turns: [_turn('t0')] });
        fireEvent.click(screen.getByRole('button', { name: 'Conversation details', exact: true }));
        expect(screen.getByTestId('chat-turns')).toHaveTextContent('1 turn');
    });

    it('shows the network indicator only when the conversation has an agent network', () => {
        renderPanel({ networkAgentCount: 0 });
        expect(screen.queryByTestId('network-indicator')).not.toBeInTheDocument();
        render(
            <ChatPanel turns={[]} onSend={vi.fn()} onStop={vi.fn()} isStreaming={false}
                networkAgentCount={3} networkRunningCount={1} onOpenNetwork={vi.fn()} />,
        );
        expect(screen.getByTestId('network-indicator')).toHaveAccessibleName('Open sub-agents (3, 1 running)');
    });

    it('surfaces context only near the current profile compaction threshold', () => {
        agentState.value = { rootId: 'r', agents: { r: { name: 'Assistant', contextUsage: { context_used: 500, context_limit: 1000, fill_ratio: .5, compaction_threshold: .9 } } } };
        const props = { turns: [], onSend: vi.fn(), onStop: vi.fn(), isStreaming: false };
        const view = render(<ChatPanel {...props} />);
        expect(screen.queryByRole('button', { name: /^Context / })).not.toBeInTheDocument();
        agentState.value.agents.r.contextUsage = { context_used: 720, context_limit: 1000, fill_ratio: .72, compaction_threshold: .8 };
        view.rerender(<ChatPanel {...props} />);
        fireEvent.click(screen.getByRole('button', { name: /^Context 72%/ }));
        expect(screen.getByTestId('context-meter')).toHaveAttribute('data-level', 'med');
        expect(screen.getByText(/At 80%, older messages/)).toBeVisible();
    });

    it('delegates conversation artifact navigation to the desktop', () => {
        const onOpenArtifacts = vi.fn();
        renderPanel({ onOpenArtifacts });

        fireEvent.click(screen.getByRole('button', { name: 'Conversation details', exact: true }));
        fireEvent.click(screen.getByTestId('conversation-artifacts-trigger'));
        expect(onOpenArtifacts).toHaveBeenCalledOnce();
    });
});
