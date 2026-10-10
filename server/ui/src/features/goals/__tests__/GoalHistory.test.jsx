import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import GoalHistory from '../GoalHistory.jsx';

const entry = (id, summary) => ({ id, summary, kind: 'progress', created_at: '2026-10-01T10:00:00Z', data: { next_action: 'Continue' } });
const response = (entries, next_before = null) => ({ ok: true, json: async () => ({ entries, next_before }) });
afterEach(() => vi.restoreAllMocks());

describe('goal history', () => {
    it('loads only on opening, pages older entries, and searches separately from current state', async () => {
        const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
            if (url.includes('q=failed')) return response([entry(1, 'Old experiment failed')]);
            if (url.includes('before=20')) return response([entry(19, 'Older result')]);
            return response([entry(20, 'Recent result')], 20);
        });
        render(<GoalHistory conversationId="chat" goalId="goal" />);
        expect(fetch).not.toHaveBeenCalled();
        fireEvent.click(screen.getByText('Goal history'));
        expect(await screen.findByText('Recent result')).toBeVisible();
        fireEvent.click(screen.getByRole('button', { name: 'Load older entries' }));
        expect(await screen.findByText('Older result')).toBeVisible();
        expect(screen.getByText('Recent result')).toBeVisible();
        fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'failed' } });
        fireEvent.click(screen.getByRole('button', { name: 'Search', exact: true }));
        expect(await screen.findByText('Old experiment failed')).toBeVisible();
        expect(screen.queryByText('Recent result')).not.toBeInTheDocument();
        expect(fetch.mock.calls.every(([url]) => url.includes('goal_id=goal'))).toBe(true);
    });

    it('ignores an older response arriving after the goal changed', async () => {
        let finishOld;
        vi.spyOn(globalThis, 'fetch').mockImplementation((url) => url.includes('goal_id=old')
            ? new Promise((resolve) => { finishOld = resolve; })
            : Promise.resolve(response([entry(2, 'New goal history')])));
        const { rerender } = render(<GoalHistory conversationId="chat" goalId="old" />);
        fireEvent.click(screen.getByText('Goal history'));
        await waitFor(() => expect(finishOld).toBeDefined());
        rerender(<GoalHistory conversationId="chat" goalId="new" />);
        expect(await screen.findByText('New goal history')).toBeVisible();
        await act(async () => finishOld(response([entry(1, 'Stale goal history')])));
        expect(screen.queryByText('Stale goal history')).not.toBeInTheDocument();
    });
});
