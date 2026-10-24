import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import useConversationSessionController from '../useConversationSessionController.js';

function deferred() {
    let resolve;
    const promise = new Promise((done) => {
        resolve = done;
    });
    return { promise, resolve };
}

function turnEndResponse() {
    const bytes = new TextEncoder().encode(
        `${JSON.stringify({ payload: { type: 'turn_end' } })}\n`,
    );
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

describe('conversation session stop handling', () => {
    afterEach(() => {
        vi.restoreAllMocks();
    });

    it.each(['network', 'HTTP'])('allows retrying Stop after a %s failure', async (failure) => {
        const chat = deferred();
        let stopCalls = 0;
        vi.spyOn(global, 'fetch').mockImplementation((url) => {
            if (url === '/api/chat') return chat.promise;
            stopCalls += 1;
            if (stopCalls === 1) {
                return failure === 'network'
                    ? Promise.reject(new TypeError('Failed to fetch'))
                    : Promise.resolve({ ok: false, status: 503 });
            }
            return Promise.resolve({ ok: true });
        });
        const { result } = renderHook(() => useConversationSessionController());
        let sendPromise;

        await act(async () => {
            sendPromise = result.current.sendMessage('hello', null, 'omnideck');
        });
        try {
            await act(async () => {
                result.current.stopGeneration();
                result.current.stopGeneration();
            });
            expect(stopCalls).toBe(1);
            expect(result.current.isStreaming).toBe(true);
            expect(result.current.stopRequested).toBe(false);

            await act(async () => {
                result.current.stopGeneration();
            });
            expect(stopCalls).toBe(2);
            expect(result.current.stopRequested).toBe(true);
        } finally {
            await act(async () => {
                chat.resolve(turnEndResponse());
                await sendPromise;
            });
        }
    });

    it('does not let a late failed Stop clear the next turn stop request', async () => {
        const chats = [deferred(), deferred()];
        const firstStop = deferred();
        let chatCalls = 0;
        let stopCalls = 0;
        vi.spyOn(global, 'fetch').mockImplementation((url) => {
            if (url === '/api/chat') return chats[chatCalls++].promise;
            stopCalls += 1;
            return stopCalls === 1 ? firstStop.promise : Promise.resolve({ ok: true });
        });
        const { result } = renderHook(() => useConversationSessionController());
        let sendPromise;
        await act(async () => {
            sendPromise = result.current.sendMessage('first', null, 'omnideck');
            result.current.stopGeneration();
        });
        await act(async () => {
            chats[0].resolve(turnEndResponse());
            await sendPromise;
        });
        await act(async () => {
            sendPromise = result.current.sendMessage('second', null, 'omnideck');
            result.current.stopGeneration();
        });
        await act(async () => {
            firstStop.resolve({ ok: false, status: 503 });
        });
        expect(result.current.isStreaming).toBe(true);
        expect(result.current.stopRequested).toBe(true);
        await act(async () => {
            chats[1].resolve(turnEndResponse());
            await sendPromise;
        });
    });

    it('keeps the UI streaming while marking stop requested', async () => {
        const chat = deferred();
        const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((url) => {
            if (url === '/api/chat') return chat.promise;
            return Promise.resolve({ ok: true });
        });
        const { result } = renderHook(() => useConversationSessionController({}));
        let sendPromise;

        await act(async () => {
            sendPromise = result.current.sendMessage('hello', null, 'omnideck');
            await Promise.resolve();
        });

        expect(result.current.isStreaming).toBe(true);

        act(() => {
            result.current.stopGeneration();
        });

        expect(result.current.isStreaming).toBe(true);
        expect(result.current.stopRequested).toBe(true);
        expect(fetchSpy).toHaveBeenCalledWith(
            expect.stringMatching(/^\/api\/chat\/stop\?conversation_id=/),
            { method: 'POST' },
        );

        await act(async () => {
            chat.resolve(turnEndResponse());
            await sendPromise;
        });
        expect(result.current.isStreaming).toBe(false);
        expect(result.current.stopRequested).toBe(false);
    });

    it('does not send nudges after stop is requested', async () => {
        const chat = deferred();
        const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((url) => {
            if (url === '/api/chat') return chat.promise;
            return Promise.resolve({ ok: true });
        });
        const { result } = renderHook(() => useConversationSessionController());
        let sendPromise;

        await act(async () => {
            sendPromise = result.current.sendMessage('hello', null, 'omnideck');
            await Promise.resolve();
        });

        act(() => {
            result.current.stopGeneration();
        });

        let nudgeResult;
        await act(async () => {
            nudgeResult = await result.current.sendNudge('wait');
        });

        expect(fetchSpy.mock.calls.filter(([url]) => url === '/api/nudge')).toHaveLength(0);
        expect(nudgeResult).toBeNull();

        await act(async () => {
            chat.resolve(turnEndResponse());
            await sendPromise;
        });
    });

    it('does not send stop or nudge requests while offline', async () => {
        let online = true;
        vi.spyOn(window.navigator, 'onLine', 'get').mockImplementation(() => online);
        const chat = deferred();
        const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((url) => {
            if (url === '/api/chat') return chat.promise;
            return Promise.resolve({ ok: true });
        });
        const { result } = renderHook(() => useConversationSessionController());
        let sendPromise;

        await act(async () => {
            sendPromise = result.current.sendMessage('hello', null, 'omnideck');
            await Promise.resolve();
        });
        expect(result.current.isStreaming).toBe(true);

        online = false;
        act(() => {
            window.dispatchEvent(new Event('offline'));
            result.current.stopGeneration();
        });

        let nudgeResult;
        await act(async () => {
            nudgeResult = await result.current.sendNudge('wait');
        });

        expect(result.current.isOffline).toBe(true);
        expect(result.current.stopRequested).toBe(false);
        expect(nudgeResult).toBeNull();
        expect(fetchSpy.mock.calls.filter(([url]) => (
            url.startsWith('/api/chat/stop') || url === '/api/nudge'
        ))).toHaveLength(0);

        online = true;
        act(() => window.dispatchEvent(new Event('online')));
        await act(async () => {
            chat.resolve(turnEndResponse());
            await sendPromise;
        });
    });
});
