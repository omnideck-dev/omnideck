import { useState } from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import GoalHistory, { groupHistory } from '../GoalHistory.jsx';

// Local times, so day headers do not depend on the machine's zone.
const at = (day, hour) => new Date(2026, 9, day, hour).toISOString();
const entry = (id, summary, fields = {}) => ({
    id, summary, kind: 'summary', actor: 'agent', claim_id: null, created_at: at(1, 10), data: {}, ...fields,
});
const response = (entries, next_before = null) => ({ ok: true, json: async () => ({ entries, next_before }) });
afterEach(() => vi.restoreAllMocks());

function History({ startOpen = false, ...props }) {
    const [open, setOpen] = useState(startOpen);
    return <GoalHistory conversationId="chat" goalId="goal" revision={1} {...props} open={open} onOpenChange={setOpen} />;
}

describe('goal history', () => {
    it('loads only on opening, pages older entries, and filters as you type', async () => {
        const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
            if (url.includes('q=failed')) return response([entry(1, 'Old experiment failed')]);
            if (url.includes('before=20')) return response([entry(19, 'Older result')]);
            return response([entry(20, 'Recent result')], 20);
        });
        render(<History />);
        expect(fetch).not.toHaveBeenCalled();
        fireEvent.click(screen.getByText('Goal history'));
        expect(await screen.findByText('Recent result')).toBeVisible();
        fireEvent.click(screen.getByRole('button', { name: 'Load older entries' }));
        expect(await screen.findByText('Older result')).toBeVisible();
        expect(screen.getByText('Recent result')).toBeVisible();
        expect(screen.queryByRole('button', { name: 'Search', exact: true })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: /Refresh/ })).not.toBeInTheDocument();
        fireEvent.change(screen.getByRole('searchbox', { name: 'Search goal history' }), { target: { value: 'failed' } });
        expect(await screen.findByText('Old experiment failed')).toBeVisible();
        expect(screen.queryByText('Recent result')).not.toBeInTheDocument();
        expect(fetch.mock.calls.every(([url]) => url.includes('goal_id=goal'))).toBe(true);
    });

    it('reloads the newest page by itself when the goal changes', async () => {
        let entries = [entry(1, 'First summary')];
        const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => response(entries));
        const view = render(<History startOpen revision={1} />);
        expect(await screen.findByText('First summary')).toBeVisible();
        entries = [entry(2, 'Second summary'), ...entries];
        view.rerender(<History startOpen revision={2} />);
        expect(await screen.findByText('Second summary')).toBeVisible();
        expect(fetch).toHaveBeenCalledTimes(2);
    });

    it('ignores an older response arriving after the goal changed', async () => {
        let finishOld;
        vi.spyOn(globalThis, 'fetch').mockImplementation((url) => url.includes('goal_id=old')
            ? new Promise((resolve) => { finishOld = resolve; })
            : Promise.resolve(response([entry(2, 'New goal history')])));
        const { rerender } = render(<History goalId="old" />);
        fireEvent.click(screen.getByText('Goal history'));
        await waitFor(() => expect(finishOld).toBeDefined());
        rerender(<History goalId="new" />);
        expect(await screen.findByText('New goal history')).toBeVisible();
        await act(async () => finishOld(response([entry(1, 'Stale goal history')])));
        expect(screen.queryByText('Stale goal history')).not.toBeInTheDocument();
    });

    it('says who did each thing', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(response([
            entry(3, 'Paused the goal.', { kind: 'state', actor: 'user' }),
            entry(2, 'Summary updated', { actor: 'agent' }),
            entry(1, 'Started the goal.', { kind: 'state', actor: 'system' }),
        ]));
        render(<History startOpen />);
        await screen.findByText('Paused the goal.');
        const rows = screen.getAllByTestId('goal-history-entry');
        expect(rows.map((row) => row.textContent)).toEqual([
            expect.stringContaining('YouPaused the goal.'),
            expect.stringContaining('AgentSummary updated'),
            expect.stringContaining('AppStarted the goal.'),
        ]);
    });

    it('shows one entry per run with the agent note as the main line and the run changes folded under it', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(response([
            entry(5, 'Called the parks office. Booked 11 AM to 4 PM.', { kind: 'note', claim_id: 'run-2' }),
            entry(4, 'Plan updated', { kind: 'plan', claim_id: 'run-2', data: { changes: ['Book the pavilion: done.'] } }),
            entry(3, 'Summary updated', { claim_id: 'run-2', data: { after: { summary: 'Pavilion booked for Saturday.' } } }),
            entry(2, 'Old change without a run', { kind: 'goal', actor: 'user', data: { after: { objective: 'Book the pavilion' } } }),
        ]));
        render(<History startOpen />);
        await screen.findByText('Called the parks office. Booked 11 AM to 4 PM.');
        const rows = screen.getAllByTestId('goal-history-entry');
        expect(rows).toHaveLength(2);
        expect(within(rows[0]).getByText('Agent')).toBeInTheDocument();
        const fold = within(rows[0]).getByText('Details').closest('details');
        expect(fold).not.toHaveAttribute('open');
        expect(fold).toHaveTextContent('Plan updated Book the pavilion: done.');
        expect(fold).toHaveTextContent('Summary updated Pavilion booked for Saturday.');
        expect(rows[1]).toHaveTextContent('YouOld change without a run');
        expect(within(rows[1]).queryByText('Details')).not.toBeInTheDocument();
    });

    it('shows a run without a note by what ended it', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(response([
            entry(2, 'The run stopped with an error.', { kind: 'state', actor: 'system', claim_id: 'run-1',
                data: { after: { next: { kind: 'error', message: 'Rate limit reached (429).' } } } }),
            entry(1, 'Plan updated', { kind: 'plan', claim_id: 'run-1', data: { changes: ['Call the office: in progress.'] } }),
        ]));
        render(<History startOpen />);
        const [row] = await screen.findAllByTestId('goal-history-entry');
        expect(row).toHaveTextContent('AppThe run stopped with an error.');
        expect(row).toHaveTextContent('Rate limit reached (429).');
        expect(within(row).getByText('Details').closest('details')).toHaveTextContent('Plan updated');
    });

    it('puts a day header before the first entry of each day', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(response([
            entry(3, 'Booked the pavilion.', { created_at: at(24, 9) }),
            entry(2, 'Asked about the date.', { created_at: at(23, 16) }),
            entry(1, 'Started the goal.', { created_at: at(23, 9) }),
        ]));
        render(<History startOpen />);
        await screen.findByText('Booked the pavilion.');
        const headers = screen.getAllByTestId('day-header');
        expect(headers).toHaveLength(2);
        const rows = screen.getAllByTestId('goal-history-entry');
        expect(within(rows[0]).getByTestId('day-header')).toBeInTheDocument();
        expect(within(rows[1]).getByTestId('day-header')).toBeInTheDocument();
        expect(within(rows[2]).queryByTestId('day-header')).not.toBeInTheDocument();
    });

    it('says when a search finds nothing', async () => {
        vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => response(url.includes('q=zzz') ? [] : [entry(1, 'Something')]));
        render(<History startOpen />);
        await screen.findByText('Something');
        fireEvent.change(screen.getByRole('searchbox', { name: 'Search goal history' }), { target: { value: 'zzz' } });
        expect(await screen.findByText('No history matches this search.')).toBeVisible();
    });
});

describe('groupHistory', () => {
    it('keeps the last note of a run as its main line', () => {
        const groups = groupHistory([
            entry(3, 'Second note', { kind: 'note', claim_id: 'run' }),
            entry(2, 'First note', { kind: 'note', claim_id: 'run' }),
        ]);
        expect(groups).toHaveLength(1);
        expect(groups[0].line).toBe('Second note');
    });
});
