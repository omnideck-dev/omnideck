import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import RoutinesView from '../RoutinesView.jsx';

const ROUTINES = [
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
        if (u === '/api/routines') {
            return Promise.resolve({ ok: true, json: async () => ({ routines: ROUTINES }) });
        }
        if (u === '/api/runner/status') {
            return Promise.resolve({ ok: true, json: async () => ({ running_routine_ids: [] }) });
        }
        if (u.startsWith('/api/routines/')) {
            return Promise.resolve({ ok: true, json: async () => ({ runs: [], tasks: [] }) });
        }
        return Promise.resolve({ ok: true, json: async () => ({}) });
    });
});

afterEach(() => { vi.restoreAllMocks(); });

test('lists routines in the table', async () => {
    render(<RoutinesView />);
    await waitFor(() => expect(screen.getByText('Daily digest')).toBeInTheDocument());
    expect(screen.getByText('Weekly report')).toBeInTheDocument();
    expect(screen.getAllByTestId('routine-row')).toHaveLength(2);
});

test('shows a human-friendly schedule, not raw cron', async () => {
    render(<RoutinesView />);
    await waitFor(() => expect(screen.getByText('Daily at 9 AM')).toBeInTheDocument());
    expect(screen.queryByText('0 9 * * *')).not.toBeInTheDocument();
});

test('search filters the list', async () => {
    render(<RoutinesView />);
    await waitFor(() => expect(screen.getByText('Daily digest')).toBeInTheDocument());
    fireEvent.change(screen.getByTestId('routines-search'), { target: { value: 'weekly' } });
    expect(screen.getByText('Weekly report')).toBeInTheDocument();
    expect(screen.queryByText('Daily digest')).not.toBeInTheDocument();
});

test('clicking a routine opens its detail full-width; back returns to the list', async () => {
    render(<RoutinesView />);
    await waitFor(() => expect(screen.getByText('Daily digest')).toBeInTheDocument());

    fireEvent.click(screen.getByText('Daily digest'));
    // Full-replacement: the detail shows and the list is gone.
    expect(await screen.findByTestId('routine-detail')).toBeInTheDocument();
    expect(screen.queryByTestId('routines-list')).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('routine-detail-back'));
    await waitFor(() => expect(screen.getByTestId('routines-list')).toBeInTheDocument());
});

test('inline row delete removes the routine after a two-click confirm', async () => {
    render(<RoutinesView />);
    await waitFor(() => expect(screen.getByText('Daily digest')).toBeInTheDocument());

    const row = screen.getByText('Daily digest').closest('tr');
    const btn = within(row).getByTestId('routine-delete');

    fireEvent.click(btn); // arm — must not delete or open the detail
    expect(screen.queryByTestId('routine-detail')).not.toBeInTheDocument();
    expect(screen.getByText('Daily digest')).toBeInTheDocument();

    fireEvent.click(btn); // confirm — optimistically removes the row
    await waitFor(() => expect(screen.queryByText('Daily digest')).not.toBeInTheDocument());
});

test('with no routines, shows an empty state whose example opens a pre-seeded chat', async () => {
    global.fetch = vi.fn((url) => {
        const u = String(url);
        if (u === '/api/routines') return Promise.resolve({ ok: true, json: async () => ({ routines: [] }) });
        if (u === '/api/runner/status') return Promise.resolve({ ok: true, json: async () => ({ running_routine_ids: [] }) });
        return Promise.resolve({ ok: true, json: async () => ({}) });
    });
    const onComposeInChat = vi.fn();
    render(<RoutinesView onComposeInChat={onComposeInChat} />);

    const cards = await screen.findAllByTestId('starter-prompt');
    expect(cards).toHaveLength(4);
    expect(screen.getByText('No routines yet')).toBeInTheDocument();

    fireEvent.click(cards[0]);
    // Seeded text must instruct the agent to *create a routine*, not run the task once.
    expect(onComposeInChat).toHaveBeenCalledWith(expect.stringContaining('Create a routine'));
});
