import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import useConversationSessionController from '../useConversationSessionController.js';

const start = { id: 'start-1', type: 'agent_started', agent_id: 'root-1', agent_name: 'omnideck', depth: 0, parent_agent_id: null };
const wake = { id: 'wake-1', type: 'goal_wakeup', agent_id: 'root-1', depth: 0, reason: 'Check for new dates', next_action: 'Read calendar', goal_id: 'g1', wake_id: 'w1' };
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
            expect.objectContaining({ kind: 'goal_wakeup', reason: 'Check for new dates' }),
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
        const { result } = renderHook(() => useConversationSessionController({ keepRunningConversation: (id) => id === 'goal-chat' }));
        await act(async () => { await result.current.loadConversation('goal-chat'); });
        await act(async () => { result.current.newConversation(); });
        expect(fetch.mock.calls.some(([url]) => url.includes('/api/chat/stop'))).toBe(false);
    });
});
