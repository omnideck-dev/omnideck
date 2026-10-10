import { act, render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import GoalSessionBridge from '../GoalSessionBridge.jsx';

const state = vi.hoisted(() => ({
    goals: { enabled: true, goalsByConversation: {}, pollVersion: 0 },
    session: { activeConversationId: 'chat-1', isStreaming: false, isOffline: false },
    refresh: vi.fn(),
}));
vi.mock('../GoalsState.jsx', () => ({ useGoals: () => state.goals }));
vi.mock('../../conversation/session/ConversationSession.jsx', () => ({
    useConversationSessionState: () => state.session,
    useConversationSessionCommands: () => ({ refreshActiveConversation: state.refresh }),
}));

beforeEach(() => {
    state.goals = { enabled: true, goalsByConversation: { 'chat-1': { id: 'g1', revision: 2, running: true, run_id: 'r1' } }, pollVersion: 0 };
    state.session = { activeConversationId: 'chat-1', isStreaming: false, isOffline: false };
    state.refresh.mockReset().mockResolvedValue({});
});

describe('goal session bridge', () => {
    it('follows a background run once and refreshes again for later runs', async () => {
        const view = render(<GoalSessionBridge />);
        await act(async () => {});
        expect(state.refresh).toHaveBeenCalledTimes(1);
        state.goals.pollVersion += 1;
        view.rerender(<GoalSessionBridge />);
        await act(async () => {});
        expect(state.refresh).toHaveBeenCalledTimes(1);
        state.goals.goalsByConversation['chat-1'] = { id: 'g1', revision: 3, running: false, last_run_id: 'r2' };
        view.rerender(<GoalSessionBridge />);
        await act(async () => {});
        expect(state.refresh).toHaveBeenCalledTimes(2);
    });

    it('retries a failed refresh on the next poll and stays idle while disabled', async () => {
        state.refresh.mockResolvedValueOnce(null);
        const view = render(<GoalSessionBridge />);
        await act(async () => {});
        state.goals.pollVersion += 1;
        view.rerender(<GoalSessionBridge />);
        await act(async () => {});
        expect(state.refresh).toHaveBeenCalledTimes(2);
        state.goals.enabled = false;
        state.goals.goalsByConversation['chat-1'].revision = 4;
        view.rerender(<GoalSessionBridge />);
        await act(async () => {});
        expect(state.refresh).toHaveBeenCalledTimes(2);
    });
});
