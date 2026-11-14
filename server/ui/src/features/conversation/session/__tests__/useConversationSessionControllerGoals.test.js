import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import useConversationSessionController from '../useConversationSessionController.js';

const start = { id: 'start-1', type: 'agent_started', agent_id: 'root-1', agent_name: 'omnideck', depth: 0, parent_agent_id: null };
const wake = { id: 'wake-1', type: 'goal', agent_id: 'root-1', depth: 0, goal_id: 'g1', data: { kind: 'wakeup', wake_id: 'w1', reason: 'planned', step: 'Read calendar' } };
const iteration = { id: 'iteration-1', type: 'iteration', agent_id: 'root-1', depth: 0, content: 'The schedule is current.', tool_calls: [] };
const response = (events) => ({ ok: true, json: async () => ({ events }) });

afterEach(() => vi.restoreAllMocks());

describe('autonomous goal conversation updates', () => {
    it('fills missed background turns without clearing a draft or duplicating events', async () => {
        const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response([start]));
        const { result } = renderHook(() => useConversationSessionController());
        await act(async () => { await result.current.loadConversation('chat-1'); result.current.setDraft('Can you also add Thursday?'); });
        fetch.mockResolvedValue(response([start, wake, iteration]));
        await act(async () => { await result.current.refreshActiveConversation(); });
        await act(async () => { await result.current.refreshActiveConversation(); });
        expect(result.current.draft).toBe('Can you also add Thursday?');
        expect(result.current.turns).toHaveLength(1);
        expect(result.current.turns[0].children).toEqual([
            expect.objectContaining({ kind: 'goal_transition', transition: 'run', step: 'Read calendar' }),
            expect.objectContaining({ kind: 'iteration', content: 'The schedule is current.' }),
        ]);
    });

    it('discards a stale refresh when the user switches conversations', async () => {
        let finishOldSnapshot;
        const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response([start]));
        const { result } = renderHook(() => useConversationSessionController());
        await act(async () => { await result.current.loadConversation('chat-1'); });
        fetch.mockImplementation((url) => url.includes('/chat-1/') ? new Promise((resolve) => { finishOldSnapshot = resolve; }) : Promise.resolve(response([])));
        let refreshing;
        await act(async () => { refreshing = result.current.refreshActiveConversation(); });
        await act(async () => { await result.current.loadConversation('chat-2'); });
        await act(async () => { finishOldSnapshot(response([start, wake, iteration])); await refreshing; });
        expect(result.current.activeConversationId).toBe('chat-2');
        expect(result.current.turns).toEqual([]);
    });

    it('does not implicitly stop a goal when the user starts a different chat', async () => {
        const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response([]));
        const { result } = renderHook(() => useConversationSessionController());
        await act(async () => { await result.current.loadConversation('goal-chat'); });
        await act(async () => { result.current.newConversation(); });
        expect(fetch.mock.calls.some(([url]) => url.includes('/api/chat/stop'))).toBe(false);
    });
});

it('places a late logged goal event at its original time and deduplicates subsequent refreshes', async () => {
    const root = { ...start, timestamp: '2026-10-23T14:01:00Z' };
    const output = { ...iteration, timestamp: '2026-10-23T14:02:00Z' };
    const divider = { type: 'goal', id: 'goal_g1_history_1', goal_id: 'g1',
        data: { kind: 'started', objective: 'Keep the calendar current', resume_at: null, question_count: 0 },
        timestamp: '2026-10-23T14:00:00Z' };
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response([root, output]));
    const { result } = renderHook(() => useConversationSessionController());
    await act(async () => { await result.current.loadConversation('chat-1'); result.current.setDraft('My draft'); });
    fetch.mockResolvedValue(response([divider, root, output]));
    await act(async () => { await result.current.refreshActiveConversation(); });
    await act(async () => { await result.current.refreshActiveConversation(); });
    // A goal chat gets a day header before its first dated item.
    expect(result.current.turns.flatMap(turn => turn.children).map(item => item.id)).toEqual([`day_${divider.id}`, divider.id, output.id]);
    expect(result.current.draft).toBe('My draft');
});
