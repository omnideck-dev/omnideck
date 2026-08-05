import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import useConversationSessionController from '../useConversationSessionController.js';

const encoder = new TextEncoder();

function streamResponse(records) {
    const bytes = encoder.encode(`${records.map(JSON.stringify).join('\n')}\n`);
    let delivered = false;
    return {
        ok: true,
        body: {
            getReader: () => ({
                read: async () => {
                    if (delivered) return { done: true, value: undefined };
                    delivered = true;
                    return { done: false, value: bytes };
                },
            }),
        },
    };
}

function httpError(status, error) {
    return {
        ok: false,
        status,
        json: async () => ({ error }),
    };
}

function envelope(seq, id, type, details = {}) {
    return {
        run_id: 'run-1',
        seq,
        id,
        conversation_id: 'conversation-1',
        agent_id: 'root-1',
        agent_name: 'Root',
        depth: 0,
        payload: { type, ...details },
    };
}

const started = {
    id: 'start-1',
    type: 'agent_started',
    conversation_id: 'conversation-1',
    agent_id: 'root-1',
    agent_name: 'Root',
    parent_agent_id: null,
    depth: 0,
};
const user = {
    id: 'user-1',
    type: 'user_message',
    conversation_id: 'conversation-1',
    agent_id: 'root-1',
    depth: 0,
    content: 'hello',
    attachments: [],
};
const iteration = {
    id: 'iteration-1',
    type: 'iteration',
    conversation_id: 'conversation-1',
    agent_id: 'root-1',
    depth: 0,
    iteration_index: 0,
    content: 'complete answer',
    thinking: null,
    tool_calls: [],
};
const completed = {
    id: 'completed-1',
    type: 'agent_completed',
    conversation_id: 'conversation-1',
    agent_id: 'root-1',
    depth: 0,
    status: 'success',
};

function activeSnapshot(events = [started, user]) {
    return {
        events,
        browser_tabs: [],
        terminal: {},
        profile_id: 'profile-1',
        active_run: {
            run_id: 'run-1',
            status: 'running',
            last_seq: 3,
            resume_after_seq: 2,
        },
    };
}

describe('conversation session run reconnection', () => {
    afterEach(() => vi.restoreAllMocks());

    it('does not start or queue a new run while the browser is offline', async () => {
        let online = false;
        vi.spyOn(window.navigator, 'onLine', 'get').mockImplementation(() => online);
        const fetchSpy = vi.spyOn(global, 'fetch');
        const { result } = renderHook(() => useConversationSessionController());
        let sendResult;

        await act(async () => {
            sendResult = await result.current.sendMessage(
                'hello',
                null,
                'profile-1',
            );
        });

        expect(sendResult).toBeUndefined();
        expect(result.current.isOffline).toBe(true);
        expect(result.current.isStreaming).toBe(false);
        expect(result.current.turns).toEqual([]);
        expect(fetchSpy).not.toHaveBeenCalled();

        online = true;
        act(() => {
            window.dispatchEvent(new Event('online'));
        });

        expect(result.current.isOffline).toBe(false);
        expect(fetchSpy).not.toHaveBeenCalled();
    });

    it('does not mistake old non-transcript events for an accepted failed start', async () => {
        const existingSnapshot = {
            events: [started, user, completed],
            browser_tabs: [],
            terminal: {},
            profile_id: 'profile-1',
            active_run: null,
        };
        let resumeCount = 0;
        vi.spyOn(global, 'fetch').mockImplementation((url) => {
            if (url.endsWith('/resume')) {
                resumeCount += 1;
                return Promise.resolve({
                    ok: true,
                    json: async () => existingSnapshot,
                });
            }
            if (url === '/api/chat') {
                return Promise.reject(new TypeError('offline before response'));
            }
            throw new Error(`Unexpected request: ${url}`);
        });
        const { result } = renderHook(() => useConversationSessionController());

        await act(async () => {
            await result.current.loadConversation('conversation-1');
            await result.current.sendMessage('new message', null, 'profile-1');
        });

        expect(resumeCount).toBe(2);
        expect(result.current.turns.flatMap((turn) => turn.children)).toContainEqual(
            expect.objectContaining({
                kind: 'error',
                message: 'offline before response',
            }),
        );
    });

    it('discovers and follows the same run after the initial stream disconnects', async () => {
        const initial = [
            envelope(1, 'start-1', 'agent_started', {
                agent_id: 'root-1', agent_name: 'Root', parent_agent_id: null,
            }),
            envelope(2, 'user-1', 'user_message', {
                content: 'hello', attachments: [],
            }),
            envelope(3, 'content-1', 'content', {
                content: 'partial ', thinking: '',
            }),
        ];
        const tail = [
            envelope(4, 'iteration-1', 'iteration', {
                iteration_index: 0,
                content: 'complete answer',
                thinking: null,
                tool_calls: [],
            }),
            envelope(5, 'completed-1', 'agent_completed', { status: 'success' }),
            envelope(6, 'end-1', 'turn_end'),
        ];
        const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((url) => {
            if (url === '/api/chat') return Promise.resolve(streamResponse(initial));
            if (url.endsWith('/resume')) {
                return Promise.resolve({ ok: true, json: async () => activeSnapshot() });
            }
            if (url === '/api/chat/runs/run-1/events?after=3') {
                return Promise.resolve(streamResponse(tail));
            }
            throw new Error(`Unexpected request: ${url}`);
        });
        const { result } = renderHook(() => useConversationSessionController());
        const conversationId = result.current.activeConversationId;

        await act(async () => {
            await result.current.sendMessage('hello', null, 'profile-1');
        });

        expect(fetchSpy.mock.calls.map(([url]) => url)).toEqual([
            '/api/chat',
            `/api/conversations/sessions/${conversationId}/resume`,
            '/api/chat/runs/run-1/events?after=3',
        ]);
        expect(result.current.isStreaming).toBe(false);
        expect(result.current.turns).toEqual([expect.objectContaining({
            children: [
                expect.objectContaining({ kind: 'user_prompt', content: 'hello' }),
                expect.objectContaining({ kind: 'iteration', content: 'complete answer' }),
            ],
        })]);
    });

    it('reattaches a run discovered while restoring after a browser refresh', async () => {
        const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((url) => {
            if (url.endsWith('/resume')) {
                return Promise.resolve({ ok: true, json: async () => activeSnapshot() });
            }
            if (url === '/api/chat/runs/run-1/events?after=2') {
                return Promise.resolve(streamResponse([
                    envelope(3, 'iteration-1', 'iteration', {
                        iteration_index: 0,
                        content: 'complete answer',
                        thinking: null,
                        tool_calls: [],
                    }),
                    envelope(4, 'completed-1', 'agent_completed', { status: 'success' }),
                    envelope(5, 'end-1', 'turn_end'),
                ]));
            }
            throw new Error(`Unexpected request: ${url}`);
        });
        const { result } = renderHook(() => useConversationSessionController());
        let loaded;

        await act(async () => {
            loaded = await result.current.loadConversation('conversation-1');
            await result.current.reattachActiveRun(loaded);
        });

        expect(loaded.activeRun.run_id).toBe('run-1');
        expect(fetchSpy).toHaveBeenCalledWith(
            '/api/chat/runs/run-1/events?after=2',
            expect.objectContaining({ signal: expect.any(AbortSignal) }),
        );
        expect(result.current.turns[0].children).toEqual([
            expect.objectContaining({ kind: 'user_prompt', content: 'hello' }),
            expect.objectContaining({ kind: 'iteration', content: 'complete answer' }),
        ]);
    });

    it('refetches persisted events and sidecars when completion wins the attach race', async () => {
        let resumeCount = 0;
        const workspaceDispatch = vi.fn();
        const agentDispatch = vi.fn();
        vi.spyOn(global, 'fetch').mockImplementation((url) => {
            if (url.endsWith('/resume')) {
                resumeCount += 1;
                if (resumeCount === 1) {
                    return Promise.resolve({ ok: true, json: async () => activeSnapshot() });
                }
                return Promise.resolve({
                    ok: true,
                    json: async () => ({
                        events: [started, user, iteration, completed],
                        browser_tabs: [{
                            agent_id: 'root-1', tab_id: '7',
                            url: 'https://example.test', title: 'Example',
                            screenshot: 'latest-image',
                        }],
                        terminal: {
                            'root-1': [{
                                cmd_id: 'cmd-1', cmd: 'pwd', status: 'completed',
                                stdout: '/work', stderr: null, exit_code: 0,
                            }],
                        },
                        profile_id: 'profile-1',
                        active_run: null,
                    }),
                });
            }
            if (url === '/api/chat/runs/run-1/events?after=2') {
                return Promise.resolve(httpError(404, 'Active run not found.'));
            }
            throw new Error(`Unexpected request: ${url}`);
        });
        const { result } = renderHook(() => useConversationSessionController({
            workspaceDispatch,
            agentDispatch,
        }));
        let loaded;

        await act(async () => {
            loaded = await result.current.loadConversation('conversation-1');
            await result.current.reattachActiveRun(loaded);
        });

        expect(resumeCount).toBe(2);
        expect(result.current.isStreaming).toBe(false);
        expect(result.current.turns[0].children).toContainEqual(
            expect.objectContaining({ kind: 'iteration', content: 'complete answer' }),
        );
        expect(agentDispatch).toHaveBeenCalledWith(expect.objectContaining({
            type: 'AGENT_COMPLETED', agentId: 'root-1', status: 'success',
        }));
        expect(workspaceDispatch).toHaveBeenCalledWith(expect.objectContaining({
            type: 'UPDATE_BROWSER_SNAPSHOT',
            agentId: 'root-1',
        }));
        expect(workspaceDispatch).toHaveBeenCalledWith(expect.objectContaining({
            type: 'UPDATE_TERMINAL',
            agentId: 'root-1',
        }));
    });

    it('retries a transient network failure while following an active run', async () => {
        let followCount = 0;
        vi.spyOn(global, 'fetch').mockImplementation((url) => {
            if (url.endsWith('/resume')) {
                return Promise.resolve({ ok: true, json: async () => activeSnapshot() });
            }
            if (url === '/api/chat/runs/run-1/events?after=2') {
                followCount += 1;
                if (followCount === 1) return Promise.reject(new TypeError('offline'));
                return Promise.resolve(streamResponse([
                    envelope(3, 'end-1', 'turn_end'),
                ]));
            }
            throw new Error(`Unexpected request: ${url}`);
        });
        const { result } = renderHook(() => useConversationSessionController());
        let loaded;

        await act(async () => {
            loaded = await result.current.loadConversation('conversation-1');
            await result.current.reattachActiveRun(loaded);
        });

        expect(followCount).toBe(2);
        expect(result.current.isStreaming).toBe(false);
    });

    it('advances past a malformed sequenced record instead of replaying forever', async () => {
        vi.spyOn(global, 'fetch').mockImplementation((url) => {
            if (url.endsWith('/resume')) {
                return Promise.resolve({ ok: true, json: async () => activeSnapshot() });
            }
            if (url === '/api/chat/runs/run-1/events?after=2') {
                return Promise.resolve(streamResponse([
                    { run_id: 'run-1', seq: 3, id: 'bad-3', payload: null },
                    envelope(4, 'end-1', 'turn_end'),
                ]));
            }
            throw new Error(`Unexpected request: ${url}`);
        });
        const { result } = renderHook(() => useConversationSessionController());
        let loaded;

        await act(async () => {
            loaded = await result.current.loadConversation('conversation-1');
            await result.current.reattachActiveRun(loaded);
        });

        expect(result.current.isStreaming).toBe(false);
        expect(result.current.turns).toHaveLength(1);
    });

    it('shows a start conflict in the transcript without reconnecting', async () => {
        const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(
            httpError(409, 'This conversation already has an active run.'),
        );
        const { result } = renderHook(() => useConversationSessionController());

        await act(async () => {
            await result.current.sendMessage('different message', null, 'profile-1');
        });

        expect(fetchSpy).toHaveBeenCalledTimes(1);
        expect(result.current.isStreaming).toBe(false);
        expect(result.current.turns.flatMap((turn) => turn.children)).toContainEqual(
            expect.objectContaining({
                kind: 'error',
                message: 'This conversation already has an active run.',
            }),
        );
    });
});
