import { act, render, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { GOAL_POLL_MS, GoalsProvider, useGoals } from '../GoalsState.jsx';

const goal = { id: 'g1', conversation_id: 'other-chat', revision: 1, status: 'active', objective: 'Plan the family trip' };
const response = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe('goal catalog', () => {
    it('does not poll while experimental goals are off and stops when disabled', async () => {
        vi.useFakeTimers();
        const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response({ goals: [goal] }));
        const view = render(<GoalsProvider><span>Chat</span></GoalsProvider>);
        await act(async () => { await vi.advanceTimersByTimeAsync(GOAL_POLL_MS * 2); });
        expect(fetch).not.toHaveBeenCalled();
        view.rerender(<GoalsProvider enabled><span>Chat</span></GoalsProvider>);
        await act(async () => {});
        expect(fetch).toHaveBeenCalledTimes(1);
        view.rerender(<GoalsProvider enabled={false}><span>Chat</span></GoalsProvider>);
        await act(async () => { await vi.advanceTimersByTimeAsync(GOAL_POLL_MS * 2); });
        expect(fetch).toHaveBeenCalledTimes(1);
    });

    it('refreshes unseen conversations and preserves their terminal state', async () => {
        vi.useFakeTimers();
        const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response({ goals: [{ ...goal, running: true }] }));
        const { result } = renderHook(() => useGoals(), { wrapper: ({ children }) => <GoalsProvider enabled>{children}</GoalsProvider> });
        await act(async () => {});
        expect(result.current.goalsByConversation['other-chat'].running).toBe(true);
        fetch.mockResolvedValue(response({ goals: [{ ...goal, status: 'completed', revision: 2, running: false }] }));
        await act(async () => { await vi.advanceTimersByTimeAsync(GOAL_POLL_MS); });
        expect(result.current.goalsByConversation['other-chat']).toMatchObject({ status: 'completed', running: false });
    });

    it('does not let an earlier detail read overwrite a successful edit', async () => {
        let finishOldRead;
        vi.spyOn(globalThis, 'fetch').mockImplementation((url, options) => {
            if (options?.method === 'PATCH') return Promise.resolve(response({ goal: { ...goal, revision: 2, objective: 'Updated objective' }, running: false, history: [] }));
            return new Promise((resolve) => { finishOldRead = resolve; });
        });
        const { result } = renderHook(() => useGoals(), { wrapper: ({ children }) => <GoalsProvider>{children}</GoalsProvider> });
        let oldRead;
        await act(async () => { oldRead = result.current.loadGoal('other-chat'); });
        await act(async () => { await result.current.mutateGoal('other-chat', 'edit', { expected_revision: 1, objective: 'Updated objective' }); });
        await act(async () => { finishOldRead(response({ goal, running: false, history: [] })); await oldRead; });
        expect(result.current.goalsByConversation['other-chat'].objective).toBe('Updated objective');
    });

    it('reloads the latest revision on a conflict and still rejects the edit', async () => {
        const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation((url, options) => Promise.resolve(options?.method === 'PATCH'
            ? response({ error: 'Revision changed' }, 409)
            : response({ goal: { ...goal, revision: 3 }, running: true, history: [] })));
        const { result } = renderHook(() => useGoals(), { wrapper: ({ children }) => <GoalsProvider>{children}</GoalsProvider> });
        await act(async () => { await expect(result.current.mutateGoal('other-chat', 'edit', { expected_revision: 1 })).rejects.toMatchObject({ status: 409 }); });
        expect(result.current.goalsByConversation['other-chat'].revision).toBe(3);
        expect(fetch).toHaveBeenCalledTimes(2);
    });

    it('does not resurrect a scheduled wake from a poll sent before pause', async () => {
        let finishPoll;
        vi.spyOn(globalThis, 'fetch').mockImplementation((url) => {
            if (url === '/api/goals') return new Promise((resolve) => { finishPoll = resolve; });
            return Promise.resolve(response({ goal: { ...goal, revision: 2, status: 'paused', resume_at: null }, running: false, history: [] }));
        });
        const { result } = renderHook(() => useGoals(), { wrapper: ({ children }) => <GoalsProvider enabled>{children}</GoalsProvider> });
        await act(async () => { await result.current.mutateGoal('other-chat', 'pause', { expected_revision: 1 }); });
        await act(async () => { finishPoll(response({ goals: [{ ...goal, status: 'scheduled', resume_at: '2026-10-06T15:00:00Z' }] })); });
        expect(result.current.goalsByConversation['other-chat']).toMatchObject({ status: 'paused', resume_at: null, revision: 2 });
    });
});
