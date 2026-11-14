import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ConversationCatalogProvider } from '../../conversation/catalog/ConversationCatalog.jsx';
import GoalPanel from '../GoalPanel.jsx';
import { GoalsProvider } from '../GoalsState.jsx';
import { formatRunTime } from '../goalStatus.js';

const FUTURE = '2099-10-06T15:00:00Z';
const PAST = '2020-10-06T15:00:00Z';
const wake = (at = FUTURE, reason = 'planned') => ({ kind: 'wake', id: 'w1', at, reason });
const baseGoal = {
    id: 'g1', conversation_id: 'chat-1', objective: 'Organize our family schedule',
    revision: 4, profile_id: 'assistant', paused: false, running: false, run_id: null, last_run_id: null,
    note: 'Collected the autumn school dates.', summary: 'School starts at 8:15. Soccer is on Tuesdays.',
    next: wake(), next_step: 'Combine calendars', questions: [],
    created_at: '2026-10-01T15:00:00Z', updated_at: '2026-10-04T15:00:00Z',
    plan: [
        { id: 's1', title: 'Collect school dates', status: 'done', notes: 'Autumn dates saved', depends_on: [] },
        { id: 's2', title: 'Combine calendars', status: 'in_progress', notes: '', depends_on: ['s1'] },
        { id: 's3', title: 'Skip the old planner', status: 'skipped', notes: '', depends_on: [] },
        { id: 's4', title: 'Share the calendar', status: 'pending', notes: '', depends_on: ['s2'] },
    ],
};
let currentGoal;
let previousGoals;
const response = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });

function setup(props = {}) {
    return render(<ConversationCatalogProvider><GoalsProvider enabled><GoalPanel conversationId="chat-1" onOpenChat={vi.fn()} {...props} /></GoalsProvider></ConversationCatalogProvider>);
}

function posts() {
    return globalThis.fetch.mock.calls.filter(([, options]) => options?.method === 'POST')
        .map(([url, options]) => ({ action: url.split('/').pop(), body: JSON.parse(options.body) }));
}

function details() {
    return screen.getByTestId('goal-details');
}

beforeEach(() => {
    currentGoal = structuredClone(baseGoal);
    previousGoals = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options = {}) => {
        if (url.includes('/goal/history?')) return response({ entries: [{ id: 1, actor: 'agent', claim_id: null, created_at: '2026-10-04T15:00:00Z', summary: 'Working summary updated', kind: 'summary', data: { after: { summary: 'Collected the school schedule.' } } }], next_before: null });
        if (url === '/api/goals') return response({ goals: currentGoal ? [currentGoal] : [] });
        if (url === '/api/conversations/sessions' || url.endsWith('/folders')) return response([]);
        if (options.method === 'POST') {
            const revision = currentGoal.revision + 1;
            if (url.endsWith('/pause')) currentGoal = { ...currentGoal, paused: true, revision };
            else if (url.endsWith('/resume')) currentGoal = { ...currentGoal, paused: false, revision };
            else if (url.endsWith('/run')) currentGoal = { ...currentGoal, revision, next: wake(PAST, currentGoal.next.kind === 'error' ? 'retry' : 'run_now') };
            else if (url.endsWith('/cancel')) currentGoal = { ...currentGoal, revision, next: { kind: 'cancelled' } };
            else if (url.endsWith('/reopen')) currentGoal = { ...currentGoal, revision, paused: false, running: true, next: { kind: 'wait', question_ids: [] } };
        }
        return response({ goal: currentGoal, running: currentGoal?.running || false, history: currentGoal ? [currentGoal, ...previousGoals] : previousGoals });
    });
});
afterEach(() => vi.restoreAllMocks());

describe('goal detail view', () => {
    it('shows one status line with the reason, the objective, the plan and what the agent knows', async () => {
        setup();
        await screen.findByText(baseGoal.objective);
        const statuses = within(details()).getAllByTestId('goal-status');
        expect(statuses).toHaveLength(1);
        expect(statuses[0]).toHaveTextContent(`Resumes ${formatRunTime(FUTURE)}`);
        expect(screen.getByTestId('goal-reason')).toHaveTextContent('Collected the autumn school dates.');
        expect(screen.getByRole('region', { name: 'What the agent knows' })).toHaveTextContent(baseGoal.summary);
        expect(screen.queryByText(/Current facts/)).not.toBeInTheDocument();
        expect(screen.getByText('Collect school dates')).toBeVisible();
        expect(screen.queryByText('Collected the school schedule.')).not.toBeInTheDocument();
        fireEvent.click(screen.getByText('Goal history'));
        expect(await screen.findByText('Collected the school schedule.')).toBeVisible();
    });

    it('counts done and skipped steps in the progress bar and marks the step in progress as Now', async () => {
        setup();
        const plan = await screen.findByRole('region', { name: 'Plan' });
        const bar = within(plan).getByRole('progressbar', { name: 'Plan progress' });
        expect(bar).toHaveAttribute('aria-valuenow', '2');
        expect(bar).toHaveAttribute('aria-valuemax', '4');
        expect(plan).toHaveTextContent('2 of 4');
        const now = within(plan).getByText('Now');
        expect(now.closest('li')).toHaveTextContent('Combine calendars');
        expect(within(plan).getAllByText('Now')).toHaveLength(1);
        expect(within(plan).getByText('Depends on: Combine calendars')).toBeInTheDocument();
    });

    it('opens the editor and source chat through their callbacks', async () => {
        const onEdit = vi.fn();
        const onOpenChat = vi.fn();
        setup({ onEdit, onOpenChat });
        fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
        expect(onEdit).toHaveBeenCalledOnce();
        fireEvent.click(screen.getByRole('button', { name: 'Open chat' }));
        expect(onOpenChat).toHaveBeenCalledOnce();
    });

    it('hides Open chat when the chat is already visible', async () => {
        setup({ onOpenChat: undefined });
        await screen.findByText(baseGoal.objective);
        expect(screen.queryByRole('button', { name: 'Open chat' })).not.toBeInTheDocument();
    });

    it('keeps the view open on Escape instead of acting like a popover', async () => {
        setup();
        await screen.findByText(baseGoal.objective);
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(screen.getByRole('region', { name: 'Goal details' })).toBeVisible();
    });

    it('offers Run now for a future wake, shows Next up with the next step, and runs the goal', async () => {
        setup();
        await screen.findByText(baseGoal.objective);
        expect(screen.getByRole('button', { name: 'Pause', exact: true })).toBeVisible();
        expect(screen.queryByRole('button', { name: 'Resume', exact: true })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: /Resume now/ })).not.toBeInTheDocument();
        expect(screen.getByRole('region', { name: 'Next up' })).toHaveTextContent('Combine calendars');
        fireEvent.click(screen.getByRole('button', { name: 'Run now' }));
        await screen.findByLabelText('Goal: Starting');
        expect(posts()).toEqual([{ action: 'run', body: { goal_id: 'g1' } }]);
        expect(screen.queryByRole('button', { name: 'Run now' })).not.toBeInTheDocument();
    });

    it('shows no Next up when the wake has no step to work on', async () => {
        currentGoal.next_step = '';
        setup();
        await screen.findByText(baseGoal.objective);
        expect(screen.queryByRole('region', { name: 'Next up' })).not.toBeInTheDocument();
    });

    it('shows a failed run in a danger callout with Retry, which runs the goal', async () => {
        currentGoal.next = { kind: 'error', message: 'Rate limit reached (429).' };
        setup();
        const callout = await screen.findByTestId('goal-error');
        expect(callout).toHaveTextContent('Rate limit reached (429).');
        expect(within(details()).getByTestId('goal-status')).toHaveTextContent('Stopped by an error');
        expect(screen.queryByTestId('goal-reason')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Run now' })).not.toBeInTheDocument();
        expect(screen.queryByRole('region', { name: 'Next up' })).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Edit' })).toBeVisible();
        fireEvent.click(within(callout).getByRole('button', { name: 'Retry' }));
        await waitFor(() => expect(screen.queryByTestId('goal-error')).not.toBeInTheDocument());
        expect(posts()).toEqual([{ action: 'run', body: { goal_id: 'g1' } }]);
    });

    it('offers only Resume while paused and says when it will run', async () => {
        currentGoal.paused = true;
        setup();
        await screen.findByLabelText('Goal: Paused');
        expect(screen.getByTestId('goal-reason')).toHaveTextContent(`When you resume, it runs ${formatRunTime(FUTURE)} as planned.`);
        expect(screen.queryByRole('button', { name: 'Pause', exact: true })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Run now' })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
        expect(screen.getByRole('region', { name: 'Next up' })).toHaveTextContent('Combine calendars');
        expect(screen.getByRole('button', { name: 'Edit' })).toBeVisible();
        fireEvent.click(screen.getByRole('button', { name: 'Resume', exact: true }));
        await screen.findByRole('button', { name: 'Pause', exact: true });
        expect(posts()).toEqual([{ action: 'resume', body: { goal_id: 'g1' } }]);
    });

    it('offers only Resume on a paused goal stopped by an error', async () => {
        currentGoal.paused = true;
        currentGoal.next = { kind: 'error', message: 'Rate limit reached (429).' };
        setup();
        await screen.findByLabelText('Goal: Paused');
        expect(screen.getByRole('button', { name: 'Resume', exact: true })).toBeVisible();
        expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
        expect(screen.queryByTestId('goal-error')).not.toBeInTheDocument();
    });

    it('summarizes waiting status without duplicating the question and offers no run button', async () => {
        currentGoal.next = { kind: 'wait', question_ids: ['morning'] };
        currentGoal.note = 'I need one answer before booking.';
        currentGoal.questions = [{ id: 'morning', question: 'Which morning works for you?', choices: [], status: 'open', revision: 1, answers: [], reviewed_answer_count: 0 }];
        setup();
        await screen.findByLabelText('Goal: 1 question for you');
        expect(screen.getByTestId('goal-reason')).toHaveTextContent('I need one answer before booking.');
        expect(screen.queryByText('Which morning works for you?')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Run now' })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Resume', exact: true })).not.toBeInTheDocument();
        expect(screen.queryByRole('region', { name: 'Next up' })).not.toBeInTheDocument();
    });

    it('explains a wait with no questions', async () => {
        currentGoal.next = { kind: 'wait', question_ids: [] };
        setup();
        await screen.findByLabelText('Goal: Waiting for you');
        expect(screen.getByTestId('goal-reason')).toHaveTextContent('The agent stopped without choosing what to do next.');
    });

    it('offers no Run now while a run is going', async () => {
        currentGoal.running = true;
        currentGoal.next = wake();
        setup();
        await screen.findByLabelText('Goal: Working');
        expect(screen.queryByRole('button', { name: 'Run now' })).not.toBeInTheDocument();
        expect(screen.queryByRole('region', { name: 'Next up' })).not.toBeInTheDocument();
    });

    it('shows the outcome first for a done goal and offers Reopen and a new goal instead of Edit', async () => {
        currentGoal.next = { kind: 'done', outcome: 'The family calendar is shared and current.' };
        const onStartGoal = vi.fn();
        setup({ onStartGoal });
        const outcome = await screen.findByTestId('goal-outcome');
        expect(outcome).toHaveTextContent('The family calendar is shared and current.');
        expect(outcome.compareDocumentPosition(screen.getByRole('region', { name: 'Plan' })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        expect(screen.queryByTestId('goal-reason')).not.toBeInTheDocument();
        expect(screen.queryByRole('region', { name: 'Next up' })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Pause', exact: true })).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Reopen…' })).toBeVisible();
        fireEvent.click(screen.getByRole('button', { name: 'Start a new goal…' }));
        expect(onStartGoal).toHaveBeenCalledOnce();
        fireEvent.click(screen.getByRole('button', { name: 'More goal actions' }));
        expect(within(screen.getByRole('menu', { name: 'Goal actions' })).getAllByRole('menuitem').map((item) => item.textContent.trim()))
            .toEqual(['Open goal history']);
    });

    it('shows no callout and no Edit on a cancelled goal', async () => {
        currentGoal.next = { kind: 'cancelled' };
        setup();
        await screen.findByLabelText('Goal: Cancelled');
        expect(screen.queryByTestId('goal-outcome')).not.toBeInTheDocument();
        expect(screen.queryByTestId('goal-reason')).not.toBeInTheDocument();
        expect(screen.queryByRole('region', { name: 'Next up' })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Reopen…' })).toBeVisible();
        expect(screen.getByRole('button', { name: 'Start a new goal…' })).toBeVisible();
    });

    it('keeps Reopen and run off until the user says what still needs doing', async () => {
        currentGoal.next = { kind: 'done', outcome: 'Calendar shared.' };
        setup();
        fireEvent.click(await screen.findByRole('button', { name: 'Reopen…' }));
        const dialog = screen.getByRole('dialog');
        const submit = within(dialog).getByRole('button', { name: 'Reopen and run' });
        expect(submit).toBeDisabled();
        const text = within(dialog).getByLabelText('Tell the agent what still needs doing.');
        fireEvent.change(text, { target: { value: '   ' } });
        expect(submit).toBeDisabled();
        fireEvent.change(text, { target: { value: 'Add the swim lessons too.' } });
        expect(submit).toBeEnabled();
        fireEvent.click(submit);
        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
        expect(posts()).toEqual([{ action: 'reopen', body: { goal_id: 'g1', text: 'Add the swim lessons too.', profile_id: 'assistant' } }]);
        await screen.findByLabelText('Goal: Working');
    });

    it('leaves the goal ended when the Reopen dialog is cancelled', async () => {
        currentGoal.next = { kind: 'cancelled' };
        setup();
        fireEvent.click(await screen.findByRole('button', { name: 'Reopen…' }));
        fireEvent.change(screen.getByLabelText('Tell the agent what still needs doing.'), { target: { value: 'More work' } });
        fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }));
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(posts()).toEqual([]);
        expect(screen.getByLabelText('Goal: Cancelled')).toBeInTheDocument();
    });

    it('puts goal history and Cancel goal in the ⋯ menu', async () => {
        setup();
        fireEvent.click(await screen.findByRole('button', { name: 'More goal actions' }));
        const menu = screen.getByRole('menu', { name: 'Goal actions' });
        expect(within(menu).getAllByRole('menuitem').map((item) => item.textContent.trim())).toEqual(['Open goal history', 'Cancel goal…']);
        fireEvent.click(within(menu).getByRole('menuitem', { name: 'Open goal history' }));
        expect(screen.queryByRole('menu')).not.toBeInTheDocument();
        expect(await screen.findByText('Collected the school schedule.')).toBeVisible();
    });

    it('cancels the goal from the ⋯ menu after confirming', async () => {
        setup();
        fireEvent.click(await screen.findByRole('button', { name: 'More goal actions' }));
        fireEvent.click(screen.getByRole('menuitem', { name: 'Cancel goal' }));
        fireEvent.click(screen.getByRole('menuitem', { name: 'Cancel this goal?' }));
        await screen.findByLabelText('Goal: Cancelled');
        expect(posts()).toEqual([{ action: 'cancel', body: { goal_id: 'g1' } }]);
        expect(screen.getByRole('button', { name: 'Reopen…' })).toBeVisible();
    });

    it('pauses the goal in this conversation', async () => {
        setup();
        fireEvent.click(await screen.findByRole('button', { name: 'Pause', exact: true }));
        await screen.findByLabelText('Goal: Paused');
        expect(posts()).toEqual([{ action: 'pause', body: { goal_id: 'g1' } }]);
    });

    it('lists previous goals of the chat', async () => {
        previousGoals = [{ ...baseGoal, id: 'g0', objective: 'Plan the summer camps', next: { kind: 'done', outcome: 'Camps booked.' } }];
        setup();
        await screen.findByText('Previous goals');
        expect(screen.getByText('Plan the summer camps')).toBeInTheDocument();
        expect(screen.getByText('Camps booked.')).toBeInTheDocument();
    });

    it('explains goals and offers Start a goal when the chat has none', async () => {
        currentGoal = null;
        const onStartGoal = vi.fn();
        setup({ onStartGoal });
        expect(await screen.findByText('This chat has no goal')).toBeVisible();
        expect(screen.getByText(/keeps working on in this chat/)).toBeVisible();
        fireEvent.click(screen.getByRole('button', { name: 'Start a goal…' }));
        expect(onStartGoal).toHaveBeenCalledOnce();
    });

    it('disables mutations offline', async () => {
        setup({ isOffline: true });
        expect(await screen.findByRole('button', { name: 'Pause', exact: true })).toBeDisabled();
        expect(screen.getByRole('button', { name: 'Edit' })).toBeDisabled();
        expect(screen.getByRole('button', { name: 'Run now' })).toBeDisabled();
        expect(screen.getByRole('button', { name: 'More goal actions' })).toBeDisabled();
    });
});
