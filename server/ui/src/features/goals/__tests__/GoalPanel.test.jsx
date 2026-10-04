import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
let rejectEdit;
const response = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });

function setup() {
    return render(<ConversationCatalogProvider><GoalsProvider enabled><GoalPanel conversationId="chat-1" profileId="assistant" /></GoalsProvider></ConversationCatalogProvider>);
}

beforeEach(() => {
    currentGoal = structuredClone(baseGoal);
    rejectEdit = false;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options = {}) => {
        if (url === '/api/goals') return response({ goals: currentGoal ? [currentGoal] : [] });
        if (url === '/api/conversations/sessions' || url.endsWith('/folders')) return response([]);
        if (options.method === 'PATCH') {
            if (rejectEdit) {
                currentGoal = { ...currentGoal, revision: 5, objective: 'Agent revised objective' };
                return response({ error: 'Revision changed' }, 409);
            }
            const { expected_revision, ...edit } = JSON.parse(options.body);
            currentGoal = { ...currentGoal, ...edit, revision: expected_revision + 1 };
        } else if (options.method === 'POST') {
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
        const status = await screen.findByLabelText('Goal: Waiting');
        fireEvent.click(status.closest('button'));
        expect(screen.getByText(/Resumes/)).toHaveTextContent('Check the school calendar');
        expect(screen.getByText('1 of 2 steps done', { exact: false })).toBeInTheDocument();
        expect(screen.getByText('Collect school dates')).toBeInTheDocument();
        expect(screen.getByText('Collected the school schedule.')).toBeInTheDocument();
        expect(screen.getByText('Keep evenings free')).toBeInTheDocument();
    });

    it('assigns an ongoing goal to an empty chat using its selected agent', async () => {
        currentGoal = null;
        setup();
        fireEvent.click(await screen.findByRole('button', { name: 'Assign goal' }));
        fireEvent.change(screen.getByLabelText('Objective'), { target: { value: 'Keep our household schedule current' } });
        fireEvent.click(screen.getByRole('combobox', { name: 'Goal type' }));
        fireEvent.click(screen.getByRole('option', { name: 'Keep working over time' }));
        fireEvent.click(screen.getByRole('button', { name: 'Start goal' }));
        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
        const creation = globalThis.fetch.mock.calls.find(([url, options]) => url.endsWith('/goal') && options?.method === 'POST');
        expect(JSON.parse(creation[1].body)).toEqual({ objective: 'Keep our household schedule current', kind: 'ongoing', constraints: '', success_criteria: [], profile_id: 'assistant' });
        expect(screen.getByText('Ongoing goal', { exact: false })).toBeInTheDocument();
    });

    it('preserves the local objective and checklist when the agent edits concurrently', async () => {
        setup();
        fireEvent.click((await screen.findByLabelText('Goal: Waiting')).closest('button'));
        fireEvent.click(screen.getByRole('button', { name: 'Edit goal' }));
        fireEvent.change(screen.getByLabelText('Objective'), { target: { value: 'My revised objective' } });
        fireEvent.change(screen.getByLabelText('Step 2 title'), { target: { value: 'My next step' } });
        rejectEdit = true;
        fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
        await screen.findByText(/The agent updated this goal while you were editing/);
        expect(screen.getByLabelText('Objective')).toHaveValue('My revised objective');
        expect(screen.getByLabelText('Step 2 title')).toHaveValue('My next step');
        expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
        fireEvent.click(screen.getByRole('button', { name: 'Load latest version' }));
        expect(screen.getByLabelText('Objective')).toHaveValue('Agent revised objective');
    });

    it('saves stable plan IDs and removes dependencies on deleted steps', async () => {
        setup();
        fireEvent.click((await screen.findByLabelText('Goal: Waiting')).closest('button'));
        fireEvent.click(screen.getByRole('button', { name: 'Edit goal' }));
        fireEvent.click(screen.getByRole('button', { name: 'Remove step 1' }));
        fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
        expect(currentGoal.plan).toEqual([{ id: 's2', title: 'Combine calendars', status: 'pending', notes: '', depends_on: [] }]);
        expect(currentGoal.revision).toBe(5);
    });

    it('pauses a scheduled goal and allows an explicit resume and cancellation', async () => {
        setup();
        fireEvent.click((await screen.findByLabelText('Goal: Waiting')).closest('button'));
        fireEvent.click(screen.getByRole('button', { name: 'Pause', exact: true }));
        await screen.findByLabelText('Goal: Paused');
        const pause = globalThis.fetch.mock.calls.find(([url]) => url.endsWith('/pause'));
        expect(JSON.parse(pause[1].body)).toEqual({ goal_id: 'g1' });
        expect(screen.queryByText(/Resumes/)).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Resume', exact: true }));
        await screen.findByLabelText('Goal: Continuing');
        fireEvent.click(screen.getByRole('button', { name: 'Cancel goal' }));
        fireEvent.click(screen.getByRole('button', { name: 'Cancel this goal?' }));
        await screen.findByLabelText('Goal: Cancelled');
        expect(screen.getByRole('button', { name: 'Assign new goal' })).toBeInTheDocument();
    });
});
