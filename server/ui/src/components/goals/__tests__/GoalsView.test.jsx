import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import GoalsView from '../GoalsView.jsx';

const GOALS = [
    {
        id: 'g1', description: 'Daily digest', status: 'active', is_running: false,
        cron: '0 9 * * *', last_run_at: '2026-01-02T00:00:00Z',
    },
    {
        id: 'g2', description: 'Weekly report', status: 'paused', is_running: false,
        cron: '0 9 * * 1', last_run_at: null,
    },
];

beforeEach(() => {
    global.fetch = vi.fn((url) => {
        const u = String(url);
        if (u === '/api/goals') {
            return Promise.resolve({ ok: true, json: async () => ({ goals: GOALS }) });
        }
        if (u === '/api/runner/status') {
            return Promise.resolve({ ok: true, json: async () => ({ running_goal_ids: [] }) });
        }
        if (u.startsWith('/api/goals/')) {
            return Promise.resolve({ ok: true, json: async () => ({ runs: [], tasks: [] }) });
        }
        return Promise.resolve({ ok: true, json: async () => ({}) });
    });
});

afterEach(() => { vi.restoreAllMocks(); });

test('lists goals in the table', async () => {
    render(<GoalsView />);
    await waitFor(() => expect(screen.getByText('Daily digest')).toBeInTheDocument());
    expect(screen.getByText('Weekly report')).toBeInTheDocument();
    expect(screen.getAllByTestId('goal-row')).toHaveLength(2);
});

test('shows a human-friendly schedule, not raw cron', async () => {
    render(<GoalsView />);
    await waitFor(() => expect(screen.getByText('Daily at 9 AM')).toBeInTheDocument());
    expect(screen.queryByText('0 9 * * *')).not.toBeInTheDocument();
});

test('search filters the list', async () => {
    render(<GoalsView />);
    await waitFor(() => expect(screen.getByText('Daily digest')).toBeInTheDocument());
    fireEvent.change(screen.getByTestId('goals-search'), { target: { value: 'weekly' } });
    expect(screen.getByText('Weekly report')).toBeInTheDocument();
    expect(screen.queryByText('Daily digest')).not.toBeInTheDocument();
});

test('clicking a goal opens its detail full-width; back returns to the list', async () => {
    render(<GoalsView />);
    await waitFor(() => expect(screen.getByText('Daily digest')).toBeInTheDocument());

    fireEvent.click(screen.getByText('Daily digest'));
    // Full-replacement: the detail shows and the list is gone.
    expect(await screen.findByTestId('goal-detail')).toBeInTheDocument();
    expect(screen.queryByTestId('goals-list')).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('goal-detail-back'));
    await waitFor(() => expect(screen.getByTestId('goals-list')).toBeInTheDocument());
});
