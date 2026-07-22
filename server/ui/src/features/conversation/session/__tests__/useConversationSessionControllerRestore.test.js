import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import useConversationSessionController from '../useConversationSessionController.js';

describe('conversation session restore', () => {
    afterEach(() => vi.restoreAllMocks());

    it('rebuilds turns and restores the active root agent for nudges', async () => {
        const events = [
            {
                id: 'start-1',
                type: 'agent_started',
                agent_id: 'root-1',
                agent_name: 'omnideck',
                parent_agent_id: null,
                depth: 0,
                timestamp: '2026-01-01T00:00:00Z',
            },
            {
                id: 'user-1',
                type: 'user_message',
                agent_id: 'root-1',
                depth: 0,
                content: 'hello',
                attachments: [],
            },
            {
                id: 'tool-created-1',
                type: 'tool_created',
                agent_id: 'root-1',
                depth: 0,
                tool_name: 'example',
            },
            {
                id: 'iteration-1',
                type: 'iteration',
                agent_id: 'root-1',
                depth: 0,
                iteration_index: 0,
                content: 'world',
                thinking: null,
                tool_calls: [],
            },
        ];
        const onConversationLoaded = vi.fn();
        const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((url) => {
            if (url.endsWith('/resume')) {
                return Promise.resolve({
                    ok: true,
                    json: () => Promise.resolve({ events }),
                });
            }
            if (url === '/api/nudge') return Promise.resolve({ ok: true });
            return Promise.resolve({ ok: true, body: null });
        });
        const { result } = renderHook(() => useConversationSessionController({
            onConversationLoaded,
        }));

        await act(async () => {
            expect(await result.current.loadConversation('conversation-1')).toBe(true);
        });

        expect(result.current.turns).toEqual([expect.objectContaining({
            agentId: 'root-1',
            children: [
                expect.objectContaining({ kind: 'user_prompt', content: 'hello' }),
                expect.objectContaining({ kind: 'iteration', content: 'world' }),
            ],
        })]);
        expect(onConversationLoaded).toHaveBeenCalledWith(expect.objectContaining({ events }));

        await act(async () => {
            await result.current.sendNudge('continue');
        });
        const nudgeRequest = fetchSpy.mock.calls.find(([url]) => url === '/api/nudge');
        expect(JSON.parse(nudgeRequest[1].body)).toMatchObject({
            conversation_id: 'conversation-1',
            agent_id: 'root-1',
        });
    });
});
