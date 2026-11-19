import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import GoalsView from '../GoalsView.jsx';
import { GoalsTestProvider, emitGoal } from './goalTestProviders.jsx';

const catalog = vi.hoisted(() => ({ items: [], loading: false }));
vi.mock('../../conversation/catalog/ConversationCatalog.jsx', () => ({ useConversationCatalog: () => catalog }));

const chat = (id, title) => ({ conversation_id: id, title, started_at: '2026-11-01T00:00:00Z' });
const question = { id: 'q', question: 'Which day?', choices: [], status: 'open', revision: 1, answers: [], reviewed_answer_count: 0 };
const goal = (id, objective, fields = {}) => ({
    id: `goal-${id}`, conversation_id: id, objective, revision: 1, paused: false, plan: [], questions: [],
    next: { kind: 'wait', question_ids: [] }, created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-10T00:00:00Z', ...fields,
});

function renderView(goals, props = {}) {
    const onOpenGoal = vi.fn();
    const onStartGoal = vi.fn();
    render(<GoalsTestProvider goals={goals}><GoalsView onOpenGoal={onOpenGoal} onStartGoal={onStartGoal} {...props} /></GoalsTestProvider>);
    return { onOpenGoal, onStartGoal };
}

const objectives = () => screen.getAllByTestId('goal-row').map((row) => within(row).getAllByRole('cell')[0].firstChild.firstChild.textContent);

beforeEach(() => {
    catalog.items = [];
    catalog.loading = false;
});

describe('Goals page', () => {
    it('sorts by status in the agreed order, with scheduled goals soonest first', () => {
        catalog.items = ['done', 'later', 'sooner', 'asking', 'paused'].map((id) => chat(id, `Chat ${id}`));
        renderView([
            goal('done', 'Done goal', { next: { kind: 'done', outcome: 'Booked' } }),
            goal('later', 'Later goal', { next: { kind: 'wake', id: 'w1', at: '2099-02-01T00:00:00Z', reason: 'planned' } }),
            goal('sooner', 'Sooner goal', { next: { kind: 'wake', id: 'w2', at: '2099-01-01T00:00:00Z', reason: 'planned' } }),
            goal('asking', 'Asking goal', { next: { kind: 'wait', question_ids: ['q'] }, questions: [question] }),
            goal('paused', 'Paused goal', { paused: true }),
        ]);
        expect(objectives()).toEqual(['Asking goal', 'Sooner goal', 'Later goal', 'Paused goal', 'Done goal']);
        expect(screen.getByRole('heading', { name: /Goals/ })).toHaveTextContent('Goals· 5');
    });

    it('searches the objective and the chat title', () => {
        catalog.items = [chat('a', 'Family reunion'), chat('b', 'Dentist')];
        renderView([goal('a', 'Book the pavilion'), goal('b', 'Find a dentist')]);
        fireEvent.change(screen.getByRole('searchbox', { name: 'Search goals' }), { target: { value: 'reunion' } });
        expect(objectives()).toEqual(['Book the pavilion']);
        fireEvent.change(screen.getByRole('searchbox', { name: 'Search goals' }), { target: { value: 'nothing here' } });
        expect(screen.getByText('No goals match your search.')).toBeVisible();
    });

    it('leaves out goals whose chat is not listed', () => {
        catalog.items = [chat('a', 'Family reunion')];
        renderView([goal('a', 'Book the pavilion'), goal('archived', 'Hidden goal')]);
        expect(objectives()).toEqual(['Book the pavilion']);
    });

    it('opens the chat and the Goal tab on a row pick', () => {
        catalog.items = [chat('a', 'Family reunion')];
        const { onOpenGoal } = renderView([goal('a', 'Book the pavilion')]);
        fireEvent.click(screen.getByTestId('goal-row'));
        expect(onOpenGoal).toHaveBeenCalledWith('a');
    });

    it('updates when a goal changes', () => {
        catalog.items = [chat('a', 'Family reunion')];
        renderView([goal('a', 'Book the pavilion')]);
        emitGoal(goal('a', 'Book the pavilion', { revision: 2, next: { kind: 'done', outcome: 'Booked' } }));
        expect(within(screen.getByTestId('goal-row')).getByTestId('goal-status')).toHaveAttribute('data-status', 'done');
    });

    it('asks to start a goal from the toolbar', () => {
        catalog.items = [chat('a', 'Family reunion')];
        const { onStartGoal } = renderView([goal('a', 'Book the pavilion')]);
        fireEvent.click(screen.getByRole('button', { name: 'Start a goal…' }));
        expect(onStartGoal).toHaveBeenCalledWith('');
    });

    it('shows the four examples when there are no goals, and an example fills the goal text', () => {
        const { onStartGoal } = renderView([]);
        expect(screen.getByTestId('goals-empty')).toHaveTextContent('No goals yet');
        expect(screen.getAllByTestId('starter-prompt')).toHaveLength(4);
        fireEvent.click(screen.getByText('Plan a trip'));
        expect(onStartGoal).toHaveBeenCalledWith('Plan a 4-day trip to Chicago in May for two. Ask me about budget and dates.');
        const prompts = screen.getAllByTestId('starter-prompt');
        expect(prompts[prompts.length - 1].parentElement.nextElementSibling).toBe(screen.getByTestId('goals-start'));
        fireEvent.click(screen.getByRole('button', { name: 'Start a goal…' }));
        expect(onStartGoal).toHaveBeenLastCalledWith('');
    });
});
