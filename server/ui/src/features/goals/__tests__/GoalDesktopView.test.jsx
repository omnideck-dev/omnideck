import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import useDesktopLayout from '../../desktop/useDesktopLayout.jsx';
import { DesktopViewRuntimeProvider } from '../../desktop/DesktopViewRuntime.jsx';
import { CONVERSATION_VIEW_ID } from '../../navigation/desktopNavigationViews.js';
import GoalDesktopView, { GOAL_VIEW_ID, goalTabLabel, useGoalDesktopActions } from '../GoalDesktopView.jsx';
import { GoalsProvider } from '../GoalsState.jsx';

const state = vi.hoisted(() => ({
    session: { activeConversationId: 'chat-a', isOffline: false },
    openConversation: vi.fn(),
}));
vi.mock('../../conversation/session/ConversationSession.jsx', () => ({
    useConversationSessionState: () => state.session,
}));
vi.mock('../../conversation/catalog/ConversationCatalog.jsx', () => ({
    useConversationCatalog: () => ({
        items: [
            { conversation_id: 'chat-a', title: 'Reunion pavilion booking for Saturday' },
            { conversation_id: 'chat-b', title: 'Dentist' },
            { conversation_id: 'chat-c', title: 'No goal here' },
        ],
        refetch: vi.fn(),
    }),
}));
vi.mock('../../navigation/DesktopNavigation.jsx', () => ({
    useDesktopNavigationCommands: () => ({ openConversation: state.openConversation }),
}));
vi.mock('../../../hooks/useIsMobileViewport.js', () => ({ default: () => false }));

const goal = (conversationId, objective) => ({
    id: `goal-${conversationId}`, conversation_id: conversationId, objective, revision: 1, profile_id: 'assistant',
    paused: false, running: false, note: '', summary: '', questions: [], plan: [], next_step: '',
    next: { kind: 'wait', question_ids: [] }, created_at: '2026-10-01T15:00:00Z',
});
const GOALS = {
    'chat-a': goal('chat-a', 'Book the pavilion for Saturday'),
    'chat-b': goal('chat-b', 'Find a dentist open on Saturdays'),
};
const response = (body) => ({ ok: true, status: 200, json: async () => body });
const CHAT = { id: CONVERSATION_VIEW_ID, type: 'conversation', label: 'Chat' };

let layoutRef;
let openGoalRef;

function Shell() {
    const layout = useDesktopLayout({ initialView: CHAT });
    layoutRef = layout;
    return <DesktopViewRuntimeProvider desktopLayout={layout}>
        <GoalsProvider enabled><Content /></GoalsProvider>
    </DesktopViewRuntimeProvider>;
}

function Content() {
    const { openGoal } = useGoalDesktopActions();
    openGoalRef = openGoal;
    const view = layoutRef.model.openViewsById[GOAL_VIEW_ID];
    return view ? <GoalDesktopView view={view} /> : null;
}

function goalViews() {
    return Object.values(layoutRef.model.openViewsById).filter((view) => view.type === 'goal');
}

beforeEach(() => {
    state.session = { activeConversationId: 'chat-a', isOffline: false };
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
        if (url === '/api/goals') return response({ goals: Object.values(GOALS) });
        const match = url.match(/sessions\/([^/]+)\/goal$/);
        if (match) {
            const current = GOALS[decodeURIComponent(match[1])] || null;
            return response({ goal: current, running: false, history: current ? [current] : [] });
        }
        return response({ entries: [], next_before: null });
    });
});
afterEach(() => vi.restoreAllMocks());

describe('the Goal tab', () => {
    it('keeps one tab when openGoal is called twice', async () => {
        render(<Shell />);
        await act(async () => { openGoalRef(); });
        await act(async () => { openGoalRef(); });
        expect(goalViews()).toHaveLength(1);
        expect(goalViews()[0].id).toBe(GOAL_VIEW_ID);
        expect(layoutRef.model.tabGroups.right.activeViewId).toBe(GOAL_VIEW_ID);
    });

    it('follows the selected chat', async () => {
        const view = render(<Shell />);
        await act(async () => { openGoalRef(); });
        expect(await screen.findByText('Book the pavilion for Saturday')).toBeVisible();
        state.session = { activeConversationId: 'chat-b', isOffline: false };
        view.rerender(<Shell />);
        expect(await screen.findByText('Find a dentist open on Saturdays')).toBeVisible();
        expect(screen.queryByText('Book the pavilion for Saturday')).not.toBeInTheDocument();
        expect(goalViews()).toHaveLength(1);
    });

    it('names the tab after the first words of the chat title', async () => {
        const view = render(<Shell />);
        await act(async () => { openGoalRef(); });
        await screen.findByText('Book the pavilion for Saturday');
        expect(goalViews()[0].label).toBe('Goal · Reunion pavilion booking');
        state.session = { activeConversationId: 'chat-b', isOffline: false };
        view.rerender(<Shell />);
        await screen.findByText('Find a dentist open on Saturdays');
        expect(goalViews()[0].label).toBe('Goal · Dentist');
    });

    it('explains goals and offers Start a goal for a chat without one', async () => {
        state.session = { activeConversationId: 'chat-c', isOffline: false };
        render(<Shell />);
        await act(async () => { openGoalRef(); });
        expect(await screen.findByText('This chat has no goal')).toBeVisible();
        expect(screen.getByRole('button', { name: 'Start a goal…' })).toBeVisible();
        expect(goalViews()[0].label).toBe('Goal');
    });

    it('hides Open chat while the chat is visible', async () => {
        render(<Shell />);
        await act(async () => { openGoalRef(); });
        await screen.findByText('Book the pavilion for Saturday');
        expect(screen.queryByRole('button', { name: 'Open chat' })).not.toBeInTheDocument();
    });
});

describe('goalTabLabel', () => {
    it('uses up to three words of the title', () => {
        expect(goalTabLabel('Plan our family trip to Maine')).toBe('Goal · Plan our family');
        expect(goalTabLabel('  ')).toBe('Goal');
        expect(goalTabLabel('Supercalifragilisticexpialidocious words here')).toBe('Goal · Supercalifragilisticexp…');
    });
});
