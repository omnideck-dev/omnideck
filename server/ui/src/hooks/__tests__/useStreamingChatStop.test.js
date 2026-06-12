import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import useStreamingChat from '../useStreamingChat.js';

function deferred() {
    let resolve;
    const promise = new Promise((done) => {
        resolve = done;
    });
    return { promise, resolve };
}

describe('useStreamingChat stop handling', () => {
    afterEach(() => {
        vi.restoreAllMocks();
    });

    it('keeps the UI streaming while marking stop requested', async () => {
        const chat = deferred();
        const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((url) => {
            if (url === '/api/chat') return chat.promise;
            return Promise.resolve({ ok: true });
        });
        const { result } = renderHook(() => useStreamingChat({}));
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
            chat.resolve({ body: null });
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
        const onNudgeSent = vi.fn();
        const { result } = renderHook(() => useStreamingChat({ onNudgeSent }));
        let sendPromise;

        await act(async () => {
            sendPromise = result.current.sendMessage('hello', null, 'omnideck');
            await Promise.resolve();
        });

        act(() => {
            result.current.stopGeneration();
        });

        await act(async () => {
            await result.current.sendNudge('wait');
        });

        expect(fetchSpy.mock.calls.filter(([url]) => url === '/api/nudge')).toHaveLength(0);
        expect(onNudgeSent).not.toHaveBeenCalled();

        await act(async () => {
            chat.resolve({ body: null });
            await sendPromise;
        });
    });
});
