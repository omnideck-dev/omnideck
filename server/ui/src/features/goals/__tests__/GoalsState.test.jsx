import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { APP_EFFECT_TYPES } from '../../app/appEffectTypes.js';
import { useGoals } from '../GoalsState.jsx';
import { GoalsTestProvider, emitEffect, emitGoal } from './goalTestProviders.jsx';

const goal = {
    id: 'g1', conversation_id: 'other-chat', revision: 1, objective: 'Plan the family trip', paused: false,
    last_run_id: null, next: { kind: 'wake', id: 'w1', at: '2026-10-06T15:00:00Z', reason: 'planned' },
    questions: [], plan: [], created_at: '2026-10-01T15:00:00Z',
};
const response = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });

function useGoalsWith(goals = [goal], enabled = true) {
    return renderHook(() => useGoals(), {
        wrapper: ({ children }) => <GoalsTestProvider goals={goals} enabled={enabled}>{children}</GoalsTestProvider>,
    });
}

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe('goal catalog', () => {
    it('replaces the list on a snapshot', () => {
        const { result } = useGoalsWith([goal]);
        expect(Object.keys(result.current.goalsByConversation)).toEqual(['other-chat']);
        emitEffect(APP_EFFECT_TYPES.GOALS_SNAPSHOT, { goals: [{ ...goal, id: 'g2', conversation_id: 'new-chat' }] });
        expect(Object.keys(result.current.goalsByConversation)).toEqual(['new-chat']);
    });

    it('keeps the higher revision on a change', () => {
        const { result } = useGoalsWith([{ ...goal, revision: 3, objective: 'Newer' }]);
        emitGoal({ ...goal, revision: 2, objective: 'Older' });
        expect(result.current.goalsByConversation['other-chat'].objective).toBe('Newer');
        emitGoal({ ...goal, revision: 4, objective: 'Newest' });
        expect(result.current.goalsByConversation['other-chat'].objective).toBe('Newest');
    });

    it("is Working while the chat's running run is the goal's last run", () => {
        const { result } = useGoalsWith([{ ...goal, last_run_id: 'run-1' }]);
        expect(result.current.goalsByConversation['other-chat'].running).toBe(false);
        emitEffect(APP_EFFECT_TYPES.RUNS_STARTED, { runs: [{ conversationId: 'other-chat', runId: 'run-2' }] });
        expect(result.current.goalsByConversation['other-chat'].running).toBe(false);
        emitEffect(APP_EFFECT_TYPES.GOALS_CHANGED, { conversationId: 'other-chat', goal: { ...goal, revision: 2, last_run_id: 'run-2' } });
        expect(result.current.goalsByConversation['other-chat'].running).toBe(true);
        emitEffect(APP_EFFECT_TYPES.RUNS_FINISHED, { runs: [{ conversationId: 'other-chat', runId: 'run-2' }] });
        expect(result.current.goalsByConversation['other-chat'].running).toBe(false);
    });

    it('sets no timer and makes no request on its own', async () => {
        const timers = vi.spyOn(globalThis, 'setTimeout');
        const fetch = vi.spyOn(globalThis, 'fetch');
        useGoalsWith([goal]);
        await act(async () => {});
        expect(fetch).not.toHaveBeenCalled();
        expect(timers.mock.calls.filter(([, delay]) => delay >= 1000)).toHaveLength(0);
    });

    it('shows no goals while Goals is off', () => {
        const { result } = useGoalsWith([goal], false);
        expect(result.current.goalsByConversation).toEqual({});
    });

    it('does not let an earlier detail read overwrite a successful edit', async () => {
        let finishOldRead;
        vi.spyOn(globalThis, 'fetch').mockImplementation((url, options) => {
            if (options?.method === 'PATCH') return Promise.resolve(response({ goal: { ...goal, revision: 2, objective: 'Updated objective' }, earlier_goals: [] }));
            return new Promise((resolve) => { finishOldRead = resolve; });
        });
        const { result } = useGoalsWith([goal]);
        let oldRead;
        await act(async () => { oldRead = result.current.loadGoal('other-chat'); });
        await act(async () => { await result.current.mutateGoal('other-chat', 'edit', { expected_revision: 1, objective: 'Updated objective' }); });
        await act(async () => { finishOldRead(response({ goal, earlier_goals: [] })); await oldRead; });
        expect(result.current.goalsByConversation['other-chat'].objective).toBe('Updated objective');
    });

    it('makes no extra request after a 409', async () => {
        const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response({ error: 'Revision changed' }, 409));
        const { result } = useGoalsWith([goal]);
        await act(async () => { await expect(result.current.mutateGoal('other-chat', 'edit', { expected_revision: 1 })).rejects.toMatchObject({ status: 409 }); });
        expect(fetch).toHaveBeenCalledTimes(1);
    });

    it('drops answer drafts of ended goals and of chats that no longer have a goal', () => {
        localStorage.clear();
        localStorage.setItem('omnideck_goal_answers:other-chat:g1', JSON.stringify({ q1: { text: 'Tuesday', choice: '', revision: 1 } }));
        localStorage.setItem('omnideck_goal_answers:deleted-chat:g9', JSON.stringify({ q1: { text: 'Old', choice: '', revision: 1 } }));
        localStorage.setItem('omnideck_goal_answers:open-chat:g2', JSON.stringify({ q1: { text: 'Keep', choice: '', revision: 1 } }));
        useGoalsWith([
            { ...goal, next: { kind: 'done', outcome: 'Trip booked' } },
            { ...goal, id: 'g2', conversation_id: 'open-chat' },
        ]);
        expect(localStorage.getItem('omnideck_goal_answers:other-chat:g1')).toBeNull();
        expect(localStorage.getItem('omnideck_goal_answers:deleted-chat:g9')).toBeNull();
        expect(localStorage.getItem('omnideck_goal_answers:open-chat:g2')).not.toBeNull();
    });

    it('posts goal actions to their own routes', async () => {
        const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response({ goal, earlier_goals: [] }));
        const { result } = useGoalsWith([]);
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
