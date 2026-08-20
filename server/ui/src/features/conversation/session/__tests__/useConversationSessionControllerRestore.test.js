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
        const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((url) => {
            if (url.endsWith('/resume')) {
                return Promise.resolve({
                    ok: true,
                    json: () => Promise.resolve({ events }),
                });
            }
            if (url === '/api/nudge') return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    ok: true,
                    nudge: {
                        id: 'nudge-1',
                        agent_id: 'root-1',
                        message: 'continue',
                    },
                }),
            });
            if (url.startsWith('/api/nudges/nudge-1?')) {
                return Promise.resolve({ ok: true, status: 200 });
            }
            return Promise.resolve({ ok: true, body: null });
        });
        const { result } = renderHook(() => useConversationSessionController());

        let loaded;
        await act(async () => {
            loaded = await result.current.loadConversation('conversation-1');
        });

        expect(result.current.turns).toEqual([expect.objectContaining({
            agentId: 'root-1',
            children: [
                expect.objectContaining({ kind: 'user_prompt', content: 'hello' }),
                expect.objectContaining({ kind: 'iteration', content: 'world' }),
            ],
        })]);
        expect(loaded).toEqual(expect.objectContaining({
            conversationId: 'conversation-1',
            events,
        }));

        let nudgeResult;
        await act(async () => {
            nudgeResult = await result.current.sendNudge('continue');
        });
        expect(nudgeResult).toEqual({
            ok: true,
            message: 'continue',
            nudge: {
                id: 'nudge-1',
                agent_id: 'root-1',
                message: 'continue',
            },
        });
        expect(result.current.pendingNudges).toEqual([nudgeResult.nudge]);
        const nudgeRequest = fetchSpy.mock.calls.find(([url]) => url === '/api/nudge');
        expect(JSON.parse(nudgeRequest[1].body)).toMatchObject({
            conversation_id: 'conversation-1',
            agent_id: 'root-1',
        });

        await act(async () => {
            expect(await result.current.deleteQueuedNudge(nudgeResult.nudge))
                .toEqual({ ok: true, alreadyGone: false });
        });
        expect(result.current.pendingNudges).toEqual([]);
    });
});
