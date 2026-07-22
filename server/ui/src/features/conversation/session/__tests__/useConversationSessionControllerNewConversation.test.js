import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import useConversationSessionController from '../useConversationSessionController.js';

// A resolved /api/chat with a null body makes sendMessage run to completion
// without a real stream, which is all these tests need.
function mockChat() {
    return vi.spyOn(global, 'fetch').mockImplementation((url) => {
        if (url === '/api/chat') return Promise.resolve({ ok: true, body: null });
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
}

describe('conversation session new-conversation signal', () => {
    afterEach(() => vi.restoreAllMocks());

    it('fires onConversationStarted on the first message of a fresh conversation', async () => {
        mockChat();
        const onConversationStarted = vi.fn();
        const { result } = renderHook(() => useConversationSessionController({ onConversationStarted }));
        const convId = result.current.activeConversationId;

        await act(async () => { await result.current.sendMessage('hello', null, 'omnideck'); });

        expect(onConversationStarted).toHaveBeenCalledTimes(1);
        expect(onConversationStarted).toHaveBeenCalledWith({
            conversationId: convId,
            firstMessage: 'hello',
        });
    });

    it('does not fire again on the second message of the same conversation', async () => {
        mockChat();
        const onConversationStarted = vi.fn();
        const { result } = renderHook(() => useConversationSessionController({ onConversationStarted }));

        await act(async () => { await result.current.sendMessage('one', null, 'omnideck'); });
        await act(async () => { await result.current.sendMessage('two', null, 'omnideck'); });

        expect(onConversationStarted).toHaveBeenCalledTimes(1);
    });

    it('re-arms after newConversation so the next first message fires it', async () => {
        mockChat();
        const onConversationStarted = vi.fn();
        const { result } = renderHook(() => useConversationSessionController({ onConversationStarted }));

        await act(async () => { await result.current.sendMessage('one', null, 'omnideck'); });
        let returnedId;
        act(() => { returnedId = result.current.newConversation(); });
        const newId = result.current.activeConversationId;
        expect(returnedId).toBe(newId);
        await act(async () => { await result.current.sendMessage('two', null, 'omnideck'); });

        expect(onConversationStarted).toHaveBeenCalledTimes(2);
        expect(onConversationStarted).toHaveBeenLastCalledWith({
            conversationId: newId,
            firstMessage: 'two',
        });
    });
});
