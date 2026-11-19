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
        const goal = { id: 'g1', next: { kind: 'wait', question_ids: [] }, questions: [], plan: [] };
        const view = render(<ChatPanel {...props} goal={goal} />);
        const composer = screen.getByRole('textbox', { name: 'Message' });
        expect(screen.getByTestId('goal-headline')).toBeInTheDocument();
        fireEvent.change(composer, { target: { value: 'My unsent question' } });
        view.rerender(<ChatPanel {...props} />);
        expect(screen.queryByTestId('goal-headline')).not.toBeInTheDocument();
        view.rerender(<ChatPanel {...props} goal={goal} />);
        expect(screen.getByRole('textbox', { name: 'Message' })).toBe(composer);
        expect(composer).toHaveValue('My unsent question');
    });
    it('shows the chat title for chats with and without a goal', () => {
        const view = render(<ChatPanel title="Plan the reunion" turns={[]} onSend={vi.fn()} onStop={vi.fn()} isStreaming={false} />);
        expect(screen.getByTestId('chat-title')).toHaveTextContent('Plan the reunion');
        expect(screen.getByTestId('chat-title')).toHaveAttribute('title', 'Plan the reunion');
        view.rerender(<ChatPanel title="Plan the reunion" turns={[]} onSend={vi.fn()} onStop={vi.fn()} isStreaming={false}
            goal={{ id: 'g1', paused: true, next: { kind: 'wait', question_ids: [] }, questions: [], plan: [] }} onOpenGoal={vi.fn()} />);
        expect(screen.getByTestId('chat-title')).toHaveTextContent('Plan the reunion');
    });
    it('shows New chat before the chat is listed', () => {
        renderPanel();
        expect(screen.getByTestId('chat-title')).toHaveTextContent('New chat');
    });
    it('shows the goal button with the status and opens the Goal tab', () => {
        const onOpenGoal = vi.fn();
        const onRequestGoal = vi.fn();
        renderPanel({ goal: { id: 'g1', paused: true, next: { kind: 'wait', question_ids: [] }, questions: [], plan: [], objective: 'Plan a trip' }, onOpenGoal, onRequestGoal });
        const button = screen.getByRole('button', { name: 'Goal: Paused. Open goal details' });
        expect(button).toHaveTextContent('Paused');
        expect(button).not.toHaveTextContent('Goal');
        fireEvent.click(button);
        expect(onOpenGoal).toHaveBeenCalledOnce();
        expect(onRequestGoal).not.toHaveBeenCalled();
    });
    it('shows the same status in the header as everywhere else, with a non-blocking question count', () => {
        const at = '2099-11-14T15:00:00Z';
        renderPanel({ goal: { id: 'g1', paused: false, running: false, plan: [],
            next: { kind: 'wake', id: 'w1', at, reason: 'planned' },
            questions: [{ id: 'q1', question: 'Which park?', choices: [], status: 'open', revision: 1, answers: [], reviewed_answer_count: 0 }],
        }, onOpenGoal: vi.fn() });
        const button = screen.getByTestId('goal-headline');
        expect(button).toHaveAttribute('data-status', 'scheduled');
        expect(button).toHaveTextContent(`Resumes ${formatRunTime(at)} · 1 question`);
    });
    it('shows "Stopped by an error" in the header for a failed run', () => {
        renderPanel({ goal: { id: 'g1', paused: false, running: false, plan: [], questions: [],
            next: { kind: 'error', message: 'Rate limit reached (429).' } }, onOpenGoal: vi.fn() });
        expect(screen.getByTestId('chat-title-bar')).toHaveTextContent('Stopped by an error');
        expect(screen.getByTestId('chat-title-bar')).not.toHaveTextContent('Rate limit');
    });
    it('keeps the full working step out of the goal button and available on hover', () => {
        const step = 'Search live openings for Senior Director / VP Engineering in Austin, remote OR hybrid; capture companies and application links';
        renderPanel({ goal: { id: 'g1', paused: false, next: { kind: 'wake', id: 'w1', at: '2026-10-01T00:00:00Z', reason: 'planned' }, running: true, questions: [], plan: [
            { id: 'done', title: 'Confirm preferences', status: 'done' },
            { id: 'now', title: step, status: 'in_progress' },
        ] }, onOpenGoal: vi.fn() });
        const button = screen.getByTestId('goal-headline');
        expect(button).toHaveTextContent('Working');
        expect(button).not.toHaveTextContent(step);
        expect(button).toHaveAttribute('title', `1 of 2 steps done. Now: ${step}. Open goal details`);
    });
    it('names the agent in the details popup', () => {
        agentState.value = { rootId: 'r', agents: { r: { name: 'Omnideck' } } };
        renderPanel();
        fireEvent.click(screen.getByRole('button', { name: 'Conversation details', exact: true }));
        expect(screen.getByTestId('chat-agent')).toHaveTextContent('Agent: Omnideck');
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

    it('shows the sub-agent count and name only when the conversation has an agent network', () => {
        renderPanel({ networkAgentCount: 0 });
        expect(screen.queryByTestId('network-indicator')).not.toBeInTheDocument();
        render(
            <ChatPanel turns={[]} onSend={vi.fn()} onStop={vi.fn()} isStreaming={false}
                networkAgentCount={3} networkRunningCount={1} onOpenNetwork={vi.fn()} />,
        );
        const button = screen.getByTestId('network-indicator');
        expect(button).toHaveAccessibleName('Open sub-agents (3, 1 running)');
        expect(button).toHaveTextContent(/^3$/);
    });

    it('never shows context on the bar and shows it in the popup', () => {
        agentState.value = { rootId: 'r', agents: { r: { name: 'Assistant', contextUsage: { context_used: 720, context_limit: 1000, fill_ratio: .72, compaction_threshold: .8 } } } };
        renderPanel();
        expect(screen.queryByRole('button', { name: /^Context / })).not.toBeInTheDocument();
        expect(screen.getByTestId('chat-title-bar')).not.toHaveTextContent('72%');
        fireEvent.click(screen.getByRole('button', { name: 'Conversation details', exact: true }));
        expect(screen.getByTestId('context-meter')).toHaveAttribute('data-level', 'med');
        expect(screen.getByText(/At 80%, older messages/)).toBeVisible();
    });

    it('says context shows after the first reply when there is no usage yet', () => {
        renderPanel();
        fireEvent.click(screen.getByRole('button', { name: 'Conversation details', exact: true }));
        expect(screen.getByText("Context shows after the agent's first reply.")).toBeVisible();
    });

    it('opens Artifacts in one click', () => {
        const onOpenArtifacts = vi.fn();
        renderPanel({ onOpenArtifacts });
        fireEvent.click(screen.getByRole('button', { name: 'Artifacts in this chat' }));
        expect(onOpenArtifacts).toHaveBeenCalledOnce();
    });
});
