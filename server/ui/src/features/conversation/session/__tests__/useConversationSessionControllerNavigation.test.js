import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import useConversationSessionController from '../useConversationSessionController.js';

function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
}
const snapshot = () => ({ ok: true, json: async () => ({ events: [] }) });

function harness() {
    const loads = [];
    let streamSignal;
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((url, options) => {
        if (url === '/api/chat') {
            streamSignal = options.signal;
            return new Promise((_, reject) => {
                options.signal.addEventListener('abort', () => {
                    reject(new DOMException('Aborted', 'AbortError'));
                }, { once: true });
            });
        }
        if (url.endsWith('/resume')) {
            const load = { ...deferred(), signal: options.signal };
            loads.push(load);
            return load.promise;
        }
        return Promise.resolve({ ok: true });
    });
    const hook = renderHook(() => useConversationSessionController());
    return { ...hook, loads, fetchSpy, streamSignal: () => streamSignal };
}

afterEach(() => vi.restoreAllMocks());

describe('conversation navigation while streaming', () => {
    it.each(['HTTP', 'network'])('preserves the current stream, draft and Stop after a %s load failure', async (failure) => {
        const test = harness();
        const { result } = test;
        const originalId = result.current.activeConversationId;
        let sending;
        let loading;
        await act(async () => {
            sending = result.current.sendMessage('keep working');
            result.current.setDraft('keep this draft');
        });
        act(() => { loading = result.current.loadConversation('destination').catch((error) => error); });
        expect(result.current.isStreaming).toBe(true);
        expect(test.streamSignal().aborted).toBe(false);
        await act(async () => {
            if (failure === 'network') test.loads[0].reject(new TypeError('Failed to fetch'));
            else test.loads[0].resolve({ ok: false, status: 503, json: async () => ({}) });
            expect(await loading).toBeInstanceOf(Error);
        });
        expect(result.current.activeConversationId).toBe(originalId);
        expect(result.current.draft).toBe('keep this draft');
        expect(result.current.isStreaming).toBe(true);
        expect(test.streamSignal().aborted).toBe(false);
        await act(async () => { await result.current.stopGeneration(); });
        expect(test.fetchSpy).toHaveBeenCalledWith(`/api/chat/stop?conversation_id=${originalId}`, { method: 'POST' });
        expect(result.current.stopRequested).toBe(true);
        test.unmount();
        await sending;
    });

    it('detaches only when the latest destination has loaded', async () => {
        const test = harness();
        let sending;
        let first;
        let second;
        await act(async () => { sending = test.result.current.sendMessage('keep working'); });
        const originalId = test.result.current.activeConversationId;
        act(() => { first = test.result.current.loadConversation('first'); });
        act(() => { second = test.result.current.loadConversation('second'); });
        expect(test.loads[0].signal.aborted).toBe(true);
        expect(test.streamSignal().aborted).toBe(false);
        await act(async () => {
            test.loads[0].resolve(snapshot());
            expect(await first).toBeNull();
        });
        expect(test.result.current.activeConversationId).toBe(originalId);
        await act(async () => {
            test.loads[1].resolve(snapshot());
            await second;
            await sending;
        });
        expect(test.result.current.activeConversationId).toBe('second');
        expect(test.streamSignal().aborted).toBe(true);
        expect(test.result.current.isStreaming).toBe(false);
        test.unmount();
    });

    it('a pending load cannot replace a newly created chat', async () => {
        const test = harness();
        let loading;
        act(() => { loading = test.result.current.loadConversation('old-destination'); });
        let freshId;
        act(() => { freshId = test.result.current.newConversation({ draft: 'new task' }); });
        expect(test.loads[0].signal.aborted).toBe(true);
        await act(async () => {
            test.loads[0].resolve(snapshot());
            expect(await loading).toBeNull();
        });
        expect(test.result.current.activeConversationId).toBe(freshId);
        expect(test.result.current.draft).toBe('new task');
        test.unmount();
    });
});
