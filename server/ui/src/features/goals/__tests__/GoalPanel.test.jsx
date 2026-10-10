import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ConversationCatalogProvider } from '../../conversation/catalog/ConversationCatalog.jsx';
import GoalPanel from '../GoalPanel.jsx';
import { GoalsProvider } from '../GoalsState.jsx';

const baseGoal = {
    id: 'g1', conversation_id: 'chat-1', objective: 'Organize our family schedule', kind: 'finite',
    status: 'scheduled', revision: 4, profile_id: 'assistant', constraints: 'Keep evenings free',
    success_criteria: ['Everyone has a weekly schedule'], running: false,
    resume_at: '2026-10-06T15:00:00Z', wake_reason: 'Check the school calendar', next_action: 'Collect updated dates',
    plan: [{ id: 's1', title: 'Collect school dates', status: 'done', notes: 'Autumn dates saved', depends_on: [] }, { id: 's2', title: 'Combine calendars', status: 'pending', notes: '', depends_on: ['s1'] }],
    progress: [{ id: 'p1', created_at: '2026-10-04T15:00:00Z', summary: 'Collected the school schedule.' }],
};
let currentGoal;
const response = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });

function setup(props = {}) {
    return render(<ConversationCatalogProvider><GoalsProvider enabled><GoalPanel conversationId="chat-1" {...props} /></GoalsProvider></ConversationCatalogProvider>);
}

beforeEach(() => {
    currentGoal = structuredClone(baseGoal);
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options = {}) => {
        if (url === '/api/goals') return response({ goals: currentGoal ? [currentGoal] : [] });
        if (url === '/api/conversations/sessions' || url.endsWith('/folders')) return response([]);
        if (options.method === 'POST') {
            if (url.endsWith('/pause')) currentGoal = { ...currentGoal, status: 'paused', revision: currentGoal.revision + 1, resume_at: null };
            else if (url.endsWith('/resume')) currentGoal = { ...currentGoal, status: 'active', revision: currentGoal.revision + 1, resume_at: null };
            else if (url.endsWith('/cancel')) currentGoal = { ...currentGoal, status: 'cancelled', revision: currentGoal.revision + 1, resume_at: null };
            else currentGoal = { ...baseGoal, ...JSON.parse(options.body), revision: 1, status: 'active', resume_at: null };
        }
        return response({ goal: currentGoal, running: currentGoal?.running || false, history: currentGoal ? [currentGoal] : [] });
    });
});
afterEach(() => vi.restoreAllMocks());

describe('conversation goals', () => {
    it('shows waiting status, next wake, checklist, and progress together', async () => {
        setup();
        const status = await screen.findByLabelText('Goal: Returning later');
        fireEvent.click(status.closest('button'));
        expect(screen.getAllByText(/Back /).length).toBeGreaterThan(0);
        expect(screen.getByText('1 of 2 steps done', { exact: false })).toBeInTheDocument();
        expect(screen.getByText('Collect school dates')).toBeInTheDocument();
        fireEvent.click(screen.getByText('Progress updates'));
        expect(screen.getByText('Collected the school schedule.')).toBeVisible();
        expect(screen.getByText('Keep evenings free')).toBeInTheDocument();
    });

    it('opens the shared editor through its edit callback', async () => {
        const onEdit = vi.fn();
        setup({ onEdit });
        fireEvent.click((await screen.findByLabelText('Goal: Returning later')).closest('button'));
        fireEvent.click(screen.getByRole('button', { name: 'Change goal' }));
        expect(onEdit).toHaveBeenCalledTimes(1);
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('opens details with keyboard focus, dismisses with Escape, and restores the trigger', async () => {
        setup();
        const trigger = (await screen.findByLabelText('Goal: Returning later')).closest('button');
        expect(screen.queryByRole('region', { name: 'Goal details' })).not.toBeInTheDocument();
        fireEvent.click(trigger);
        const details = document.getElementById(trigger.getAttribute('aria-controls'));
        await waitFor(() => expect(details).toHaveFocus());
        fireEvent.keyDown(details, { key: 'Escape' });
        expect(screen.queryByRole('region', { name: 'Goal details' })).not.toBeInTheDocument();
        expect(trigger).toHaveFocus();
        fireEvent.click(trigger);
        const outerEscape = vi.fn();
        document.addEventListener('keydown', outerEscape);
        fireEvent.keyDown(trigger, { key: 'Escape' });
        expect(outerEscape).not.toHaveBeenCalled();
        document.removeEventListener('keydown', outerEscape);
        fireEvent.click(trigger);
        fireEvent.mouseDown(document.body);
        expect(screen.queryByRole('region', { name: 'Goal details' })).not.toBeInTheDocument();
    });

    it('keeps a request for input visible while the details are closed', async () => {
        currentGoal = { ...baseGoal, status: 'needs_input', resume_at: null, status_reason: 'Which morning works for you?' };
        setup();
        await screen.findByLabelText('Goal: Waiting for your answer');
        expect(screen.getByText('Which morning works for you?')).toBeInTheDocument();
        expect(screen.getByText('Reply below to continue')).toBeInTheDocument();
        expect(screen.queryByRole('region', { name: 'Goal details' })).not.toBeInTheDocument();
    });

    it('renders nothing when the chat has no assigned goal', async () => {
        currentGoal = null;
        setup();
        await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith('/api/conversations/sessions/chat-1/goal', undefined));
        expect(screen.queryByTestId('goal-panel')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Assign goal' })).not.toBeInTheDocument();
    });

    it('pauses a scheduled goal and allows an explicit resume and cancellation', async () => {
        setup();
        fireEvent.click((await screen.findByLabelText('Goal: Returning later')).closest('button'));
        fireEvent.click(screen.getByRole('button', { name: 'Pause', exact: true }));
        await screen.findByLabelText('Goal: Paused');
        const pause = globalThis.fetch.mock.calls.find(([url]) => url.endsWith('/pause'));
        expect(JSON.parse(pause[1].body)).toEqual({ goal_id: 'g1' });
        expect(screen.queryByText('Check the school calendar')).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Resume', exact: true }));
        await screen.findByLabelText('Goal: Getting started');
        fireEvent.click(screen.getByRole('button', { name: 'Cancel goal' }));
        fireEvent.click(screen.getByRole('button', { name: 'Cancel this goal?' }));
        await screen.findByLabelText('Goal: Cancelled');
        expect(screen.queryByRole('button', { name: 'Assign new goal' })).not.toBeInTheDocument();
    });
});
