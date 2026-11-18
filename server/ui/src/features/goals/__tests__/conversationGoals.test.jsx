import { render, renderHook, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { APP_EFFECT_TYPES } from '../../app/appEffectTypes.js';
import ConversationGoalStatus from '../ConversationGoalStatus.jsx';
import { useNeedsYou } from '../conversationGoals.js';
import useGoalRequests from '../useGoalRequests.js';
import { GoalsTestProvider, emitEffect } from './goalTestProviders.jsx';

vi.mock('../../conversation/session/ConversationSession.jsx', () => ({
    useConversationSessionState: () => ({ isOffline: false, stopRequested: false }),
}));
const openGoal = vi.fn();
vi.mock('../GoalDesktopView.jsx', () => ({ useGoalDesktopActions: () => ({ openGoal }) }));

const waiting = {
    id: 'g1', conversation_id: 'a', objective: 'Plan', revision: 1, paused: false, plan: [],
    questions: [{ id: 'q', question: 'Which day?', choices: [], status: 'open', revision: 1, answers: [], reviewed_answer_count: 0 }],
    next: { kind: 'wait', question_ids: ['q'] }, created_at: '2026-11-01T00:00:00Z',
};
const items = [{ conversation_id: 'a' }, { conversation_id: 'b' }];

function wrapper(goals, enabled = true) {
    return ({ children }) => <GoalsTestProvider goals={goals} enabled={enabled}>{children}</GoalsTestProvider>;
}

describe('goal helpers for the conversation list', () => {
    it('useNeedsYou returns the chats whose goal needs the user', () => {
        const { result } = renderHook(() => useNeedsYou(items), { wrapper: wrapper([waiting]) });
        expect(result.current).toEqual([{ conversation_id: 'a' }]);
    });

    it('useNeedsYou returns nothing while Goals is off', () => {
        const { result } = renderHook(() => useNeedsYou(items), { wrapper: wrapper([waiting], false) });
        expect(result.current).toEqual([]);
    });

    it('ConversationGoalStatus renders the compact status or nothing', () => {
        const Wrapper = wrapper([waiting]);
        const view = render(<Wrapper><ConversationGoalStatus conversationId="a" /></Wrapper>);
        expect(screen.getByTestId('goal-status')).toHaveAttribute('data-status', 'questions');
        view.rerender(<Wrapper><ConversationGoalStatus conversationId="b" /></Wrapper>);
        expect(screen.queryByTestId('goal-status')).not.toBeInTheDocument();
    });
});

describe('goal requests', () => {
    it('turns a start request for this chat into a dialog request with the objective', () => {
        const { result } = renderHook(() => useGoalRequests('new-chat'), { wrapper: wrapper([]) });
        expect(result.current.request).toBeNull();
        emitEffect(APP_EFFECT_TYPES.GOALS_START_REQUESTED, { conversationId: 'new-chat', objective: 'Plan a trip' });
        expect(result.current.request).toMatchObject({ conversationId: 'new-chat', objective: 'Plan a trip' });
    });

    it('focuses the Goal tab for an open goal with no new text, and opens the dialog otherwise', () => {
        const { result } = renderHook(() => useGoalRequests('a'), { wrapper: wrapper([waiting]) });
        result.current.requestGoal({ objective: '' });
        expect(openGoal).toHaveBeenCalledWith('a');
        expect(result.current.request).toBeNull();
    });
});
