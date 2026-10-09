import { useState } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ConversationCatalogProvider } from '../../conversation/catalog/ConversationCatalog.jsx';
import GoalDialog from '../GoalDialog.jsx';
import { GoalsProvider } from '../GoalsState.jsx';

const goalPath = '/api/conversations/sessions/chat-1/goal';
const baseGoal = {
    id: 'g1', conversation_id: 'chat-1', objective: 'Organize our family schedule', kind: 'finite',
    status: 'scheduled', revision: 4, profile_id: 'assistant', constraints: 'Keep evenings free',
    success_criteria: ['Everyone has a weekly schedule'], running: false,
    resume_at: '2026-10-06T15:00:00Z', wake_reason: 'Check the school calendar', next_action: 'Collect updated dates',
    plan: [{ id: 's1', title: 'Collect school dates', status: 'done', notes: 'Autumn dates saved', depends_on: [] }, { id: 's2', title: 'Combine calendars', status: 'pending', notes: '', depends_on: ['s1'] }],
    progress: [{ id: 'p1', created_at: '2026-10-04T15:00:00Z', summary: 'Collected the school schedule.' }],
};
const response = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
let currentGoal;
let rejectEdit;
let rejectCreate;
let failLoad;
let saveGate;

function DialogHarness({ onClose, shown = true, ...props }) {
    const [open, setOpen] = useState(true);
    return <ConversationCatalogProvider><GoalsProvider enabled>
        {open && shown && <GoalDialog {...props} onClose={() => { onClose(); setOpen(false); }} />}
    </GoalsProvider></ConversationCatalogProvider>;
}

function setup(props = {}) {
    const onStarted = vi.fn();
    const onClose = vi.fn();
    const dialogProps = { conversationId: 'chat-1', profileId: 'household-planner', onStarted, onClose, ...props };
    const view = render(<DialogHarness {...dialogProps} />);
    return { onStarted, onClose, hideDialog: () => view.rerender(<DialogHarness {...dialogProps} shown={false} />) };
}

function mutations() {
    return globalThis.fetch.mock.calls.filter(([url, options]) => url === goalPath && ['POST', 'PATCH'].includes(options?.method));
}

beforeEach(() => {
    currentGoal = structuredClone(baseGoal);
    rejectEdit = false;
    rejectCreate = 0;
    failLoad = false;
    saveGate = undefined;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options = {}) => {
        if (url === '/api/goals') return response({ goals: currentGoal ? [currentGoal] : [] });
        if (url === '/api/conversations/sessions' || url.endsWith('/folders')) return response([]);
        if (url !== goalPath) throw new Error(`Unexpected goal request: ${url}`);
        if (!options.method && failLoad) return response({ error: 'Goal could not be loaded' }, 503);
        if (saveGate && ['POST', 'PATCH'].includes(options.method)) await saveGate;
        if (options.method === 'PATCH') {
            if (rejectEdit) {
                currentGoal = { ...currentGoal, revision: 5, objective: 'Agent revised objective' };
                return response({ error: 'Revision changed' }, 409);
            }
            const { expected_revision, ...edit } = JSON.parse(options.body);
            currentGoal = { ...currentGoal, ...edit, revision: expected_revision + 1 };
        } else if (options.method === 'POST') {
            if (rejectCreate === 409) {
                currentGoal = { ...structuredClone(baseGoal), revision: 9, objective: 'Goal assigned in another window' };
                return response({ error: 'This conversation already has an unfinished goal' }, 409);
            }
            if (rejectCreate) return response({ error: 'Could not start the goal' }, rejectCreate);
            currentGoal = { ...baseGoal, ...JSON.parse(options.body), revision: 1, status: 'active', resume_at: null };
        }
        return response({ goal: currentGoal, running: currentGoal?.running || false, history: currentGoal ? [currentGoal] : [] });
    });
});
afterEach(() => vi.restoreAllMocks());

describe('goal assignment dialog', () => {
    it('prefills a new objective and assigns an ongoing goal using the selected agent', async () => {
        currentGoal = null;
        const callbacks = setup({ initialObjective: 'Keep our household schedule current' });
        expect(await screen.findByLabelText('What would you like done?')).toHaveValue('Keep our household schedule current');
        expect(callbacks.onStarted).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('combobox', { name: 'Goal type' }));
        fireEvent.click(screen.getByRole('option', { name: 'Ongoing' }));
        fireEvent.click(screen.getByRole('button', { name: 'Start goal' }));
        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
        expect(mutations()).toHaveLength(1);
        expect(mutations()[0][1].method).toBe('POST');
        expect(JSON.parse(mutations()[0][1].body)).toEqual({
            objective: 'Keep our household schedule current', kind: 'ongoing', profile_id: 'household-planner',
        });
        expect(callbacks.onStarted).toHaveBeenCalledTimes(1);
        expect(callbacks.onClose).toHaveBeenCalledTimes(1);
    });

    it.each(['active', 'paused', 'scheduled', 'needs_input'])('edits a %s goal without replacing its objective or resuming it', async (status) => {
        currentGoal.status = status;
        const callbacks = setup({ initialObjective: 'A different request from the composer' });
        expect(await screen.findByLabelText('What would you like done?')).toHaveValue(`${baseGoal.objective}\n\nLimits and preferences:\n${baseGoal.constraints}\n\nDone when:\n${baseGoal.success_criteria.join('\n')}`);
        expect(screen.getByRole('heading', { name: 'Edit goal' })).toBeInTheDocument();
        expect(screen.queryByRole('combobox', { name: 'Goal type' })).not.toBeInTheDocument();
        expect(screen.queryByLabelText('Constraints')).not.toBeInTheDocument();
        expect(screen.queryByLabelText('Success criteria')).not.toBeInTheDocument();
        const description = screen.getByLabelText('What would you like done?').value + '\nKeep mornings free too';
        fireEvent.change(screen.getByLabelText('What would you like done?'), { target: { value: description } });
        fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
        await waitFor(() => expect(callbacks.onStarted).toHaveBeenCalledTimes(1));
        const edit = mutations()[0];
        expect(edit[1].method).toBe('PATCH');
        expect(JSON.parse(edit[1].body)).toEqual({
            expected_revision: 4, objective: description, constraints: '',
            success_criteria: [], plan: baseGoal.plan,
        });
        expect(currentGoal.status).toBe(status);
        expect(currentGoal.profile_id).toBe('assistant');
        expect(callbacks.onClose).toHaveBeenCalledTimes(1);
    });

    it.each(['completed', 'cancelled'])('starts a fresh draft after a %s goal', async (status) => {
        currentGoal.status = status;
        setup({ initialObjective: 'Plan next month’s meals' });
        expect(await screen.findByLabelText('What would you like done?')).toHaveValue('Plan next month’s meals');
        expect(screen.getByRole('button', { name: 'Start goal' })).toBeInTheDocument();
        expect(screen.queryByLabelText('Step 1 title')).not.toBeInTheDocument();
        expect(screen.queryByLabelText('Constraints')).not.toBeInTheDocument();
    });

    it('preserves local objective and checklist edits after an agent revision conflict', async () => {
        const callbacks = setup();
        fireEvent.change(await screen.findByLabelText('What would you like done?'), { target: { value: 'My revised objective' } });
        fireEvent.change(screen.getByLabelText('Step 2 title'), { target: { value: 'My next step' } });
        rejectEdit = true;
        fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
        await screen.findByText(/goal changed while you were editing/);
        expect(screen.getByLabelText('What would you like done?')).toHaveValue('My revised objective');
        expect(screen.getByLabelText('Step 2 title')).toHaveValue('My next step');
        expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
        expect(callbacks.onStarted).not.toHaveBeenCalled();
        expect(callbacks.onClose).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('button', { name: 'Load latest version' }));
        await waitFor(() => expect(screen.getByLabelText('What would you like done?')).toHaveValue(`Agent revised objective\n\nLimits and preferences:\n${baseGoal.constraints}\n\nDone when:\n${baseGoal.success_criteria.join('\n')}`));
        rejectEdit = false;
        fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
        await waitFor(() => expect(callbacks.onStarted).toHaveBeenCalledTimes(1));
        expect(JSON.parse(mutations()[1][1].body).expected_revision).toBe(5);
    });

    it('saves stable checklist IDs and removes dependencies on a deleted step', async () => {
        const callbacks = setup();
        await screen.findByLabelText('What would you like done?');
        fireEvent.click(screen.getByRole('button', { name: 'Remove step 1' }));
        fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
        await waitFor(() => expect(callbacks.onStarted).toHaveBeenCalledTimes(1));
        expect(currentGoal.plan).toEqual([{ id: 's2', title: 'Combine calendars', status: 'pending', notes: '', depends_on: [] }]);
        expect(currentGoal.revision).toBe(5);
    });

    it('retries a failed load without offering accidental goal creation', async () => {
        failLoad = true;
        const callbacks = setup();
        await screen.findByText('Goal could not be loaded');
        expect(screen.queryByLabelText('What would you like done?')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Start goal' })).not.toBeInTheDocument();
        expect(mutations()).toHaveLength(0);
        expect(callbacks.onStarted).not.toHaveBeenCalled();
        failLoad = false;
        fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
        expect(await screen.findByLabelText('What would you like done?')).toHaveValue(`${baseGoal.objective}\n\nLimits and preferences:\n${baseGoal.constraints}\n\nDone when:\n${baseGoal.success_criteria.join('\n')}`);
        expect(screen.getByRole('button', { name: 'Save changes' })).toBeInTheDocument();
        expect(mutations()).toHaveLength(0);
    });

    it('reports start success only after a failed creation has been retried successfully', async () => {
        currentGoal = null;
        rejectCreate = 503;
        const callbacks = setup({ initialObjective: 'Plan household meals' });
        await screen.findByLabelText('What would you like done?');
        fireEvent.click(screen.getByRole('button', { name: 'Start goal' }));
        await screen.findByText('Could not start the goal');
        expect(callbacks.onStarted).not.toHaveBeenCalled();
        expect(callbacks.onClose).not.toHaveBeenCalled();
        expect(screen.getByLabelText('What would you like done?')).toHaveValue('Plan household meals');
        rejectCreate = 0;
        fireEvent.click(screen.getByRole('button', { name: 'Start goal' }));
        await waitFor(() => expect(callbacks.onStarted).toHaveBeenCalledTimes(1));
        expect(callbacks.onClose).toHaveBeenCalledTimes(1);
    });

    it('reloads an assignment conflict into editing the existing goal before saving again', async () => {
        currentGoal = null;
        rejectCreate = 409;
        const callbacks = setup({ initialObjective: 'My proposed goal' });
        await screen.findByLabelText('What would you like done?');
        fireEvent.click(screen.getByRole('button', { name: 'Start goal' }));
        await screen.findByText(/goal changed while you were editing/);
        expect(screen.getByLabelText('What would you like done?')).toHaveValue('My proposed goal');
        expect(callbacks.onStarted).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('button', { name: 'Load latest version' }));
        await screen.findByRole('button', { name: 'Save changes' });
        expect(screen.getByLabelText('What would you like done?')).toHaveValue(`Goal assigned in another window\n\nLimits and preferences:\n${baseGoal.constraints}\n\nDone when:\n${baseGoal.success_criteria.join('\n')}`);
        rejectCreate = 0;
        fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
        await waitFor(() => expect(callbacks.onStarted).toHaveBeenCalledTimes(1));
        expect(mutations().map(([, options]) => options.method)).toEqual(['POST', 'PATCH']);
        expect(JSON.parse(mutations()[1][1].body).expected_revision).toBe(9);
    });

    it('ignores a pending save callback after its dialog has been unmounted', async () => {
        currentGoal = null;
        let resolveSave;
        saveGate = new Promise((resolve) => { resolveSave = resolve; });
        const callbacks = setup({ initialObjective: 'Plan household meals' });
        await screen.findByLabelText('What would you like done?');
        fireEvent.click(screen.getByRole('button', { name: 'Start goal' }));
        await waitFor(() => expect(mutations()).toHaveLength(1));
        callbacks.hideDialog();
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        await act(async () => { resolveSave(); });
        expect(callbacks.onStarted).not.toHaveBeenCalled();
        expect(callbacks.onClose).not.toHaveBeenCalled();
    });

    it('closing without saving never starts a goal', async () => {
        currentGoal = null;
        const callbacks = setup();
        await screen.findByLabelText('What would you like done?');
        fireEvent.click(screen.getByRole('button', { name: 'Cancel', exact: true }));
        expect(callbacks.onClose).toHaveBeenCalledTimes(1);
        expect(callbacks.onStarted).not.toHaveBeenCalled();
        expect(mutations()).toHaveLength(0);
    });
});
