import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import useConversationSessionController from '../useConversationSessionController.js';

describe('conversation session new conversation', () => {
    afterEach(() => vi.restoreAllMocks());

    it('switches identifiers, resets the transcript, and seeds the next draft', async () => {
        const events = [
            {
                id: 'start-1',
                type: 'agent_started',
                agent_id: 'root-1',
                agent_name: 'Root',
                parent_agent_id: null,
                depth: 0,
            },
            {
                id: 'iteration-1',
                type: 'iteration',
                agent_id: 'root-1',
                depth: 0,
                iteration_index: 0,
                content: 'finished answer',
                thinking: null,
                tool_calls: [],
            },
        ];
        vi.spyOn(global, 'fetch').mockImplementation((url) => {
            if (url.endsWith('/resume')) {
                return Promise.resolve({
                    ok: true,
                    json: () => Promise.resolve({ events }),
                });
            }
            return Promise.resolve({ ok: true });
        });
        const { result } = renderHook(() => useConversationSessionController());

        await act(async () => {
            await result.current.loadConversation('existing-conversation');
        });
        expect(result.current.turns).toHaveLength(1);

        let nextId;
        act(() => {
            nextId = result.current.newConversation({ draft: 'next task' });
        });

        expect(nextId).not.toBe('existing-conversation');
        expect(result.current.activeConversationId).toBe(nextId);
        expect(result.current.turns).toEqual([]);
        expect(result.current.draft).toBe('next task');
    });
});
