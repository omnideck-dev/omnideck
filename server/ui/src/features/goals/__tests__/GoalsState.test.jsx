import { act, render, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { GOAL_POLL_MS, GoalsProvider, useGoals } from '../GoalsState.jsx';

const goal = {
    id: 'g1', conversation_id: 'other-chat', revision: 1, objective: 'Plan the family trip', paused: false, running: false,
    next: { kind: 'wake', id: 'w1', at: '2026-10-06T15:00:00Z', reason: 'planned' }, questions: [], plan: [],
};
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
        fetch.mockResolvedValue(response({ goals: [{ ...goal, next: { kind: 'done', outcome: 'Trip booked' }, revision: 2, running: false }] }));
        await act(async () => { await vi.advanceTimersByTimeAsync(GOAL_POLL_MS); });
        expect(result.current.goalsByConversation['other-chat']).toMatchObject({ next: { kind: 'done', outcome: 'Trip booked' }, running: false });
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
            return Promise.resolve(response({ goal: { ...goal, revision: 2, paused: true }, running: false, history: [] }));
        });
        const { result } = renderHook(() => useGoals(), { wrapper: ({ children }) => <GoalsProvider enabled>{children}</GoalsProvider> });
        await act(async () => { await result.current.mutateGoal('other-chat', 'pause', { expected_revision: 1 }); });
        await act(async () => { finishPoll(response({ goals: [{ ...goal, paused: false }] })); });
        expect(result.current.goalsByConversation['other-chat']).toMatchObject({ paused: true, revision: 2 });
    });

    it('keeps the same goals object across two identical polls', async () => {
        vi.useFakeTimers();
        const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => response({ goals: [structuredClone(goal)] }));
        const { result } = renderHook(() => useGoals(), { wrapper: ({ children }) => <GoalsProvider enabled>{children}</GoalsProvider> });
        await act(async () => {});
        const first = result.current.goalsByConversation;
        expect(first['other-chat']).toMatchObject({ id: 'g1', revision: 1 });
        await act(async () => { await vi.advanceTimersByTimeAsync(GOAL_POLL_MS); });
        expect(fetch).toHaveBeenCalledTimes(2);
        expect(result.current.goalsByConversation).toBe(first);
        fetch.mockImplementation(async () => response({ goals: [{ ...structuredClone(goal), revision: 2 }] }));
        await act(async () => { await vi.advanceTimersByTimeAsync(GOAL_POLL_MS); });
        expect(result.current.goalsByConversation).not.toBe(first);
        expect(result.current.goalsByConversation['other-chat'].revision).toBe(2);
    });

    it('drops answer drafts of ended goals and of chats that no longer have a goal', async () => {
        localStorage.clear();
        localStorage.setItem('omnideck_goal_answers:other-chat:g1', JSON.stringify({ q1: { text: 'Tuesday', choice: '', revision: 1 } }));
        localStorage.setItem('omnideck_goal_answers:deleted-chat:g9', JSON.stringify({ q1: { text: 'Old', choice: '', revision: 1 } }));
        localStorage.setItem('omnideck_goal_answers:open-chat:g2', JSON.stringify({ q1: { text: 'Keep', choice: '', revision: 1 } }));
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(response({ goals: [
            { ...goal, next: { kind: 'done', outcome: 'Trip booked' } },
            { ...goal, id: 'g2', conversation_id: 'open-chat' },
        ] }));
        renderHook(() => useGoals(), { wrapper: ({ children }) => <GoalsProvider enabled>{children}</GoalsProvider> });
        await act(async () => {});
        expect(localStorage.getItem('omnideck_goal_answers:other-chat:g1')).toBeNull();
        expect(localStorage.getItem('omnideck_goal_answers:deleted-chat:g9')).toBeNull();
        expect(localStorage.getItem('omnideck_goal_answers:open-chat:g2')).not.toBeNull();
    });

    it('posts goal actions to their own routes', async () => {
        const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response({ goal, running: false, history: [] }));
        const { result } = renderHook(() => useGoals(), { wrapper: ({ children }) => <GoalsProvider>{children}</GoalsProvider> });
        for (const action of ['pause', 'resume', 'run', 'cancel', 'reopen']) {
            await act(async () => { await result.current.mutateGoal('other-chat', action, { goal_id: 'g1' }); });
        }
        expect(fetch.mock.calls.map(([url, options]) => `${options.method} ${url}`)).toEqual([
            'POST /api/conversations/sessions/other-chat/goal/pause',
            'POST /api/conversations/sessions/other-chat/goal/resume',
            'POST /api/conversations/sessions/other-chat/goal/run',
            'POST /api/conversations/sessions/other-chat/goal/cancel',
            'POST /api/conversations/sessions/other-chat/goal/reopen',
        ]);
    });
});
