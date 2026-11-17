import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import useSavedThinking from '../useSavedThinking.js';

const a = { conversationId: 'chat-a', eventId: 'event-a' };
const b = { conversationId: 'chat-a', eventId: 'event-b' };
afterEach(() => vi.unstubAllGlobals());

describe('useSavedThinking', () => {
    it('batches expanded entries and keeps loaded text when closed and reopened', async () => {
        const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ 'event-a': 'First', 'event-b': 'Second' }) });
        vi.stubGlobal('fetch', fetch);
        const { result, rerender } = renderHook(({ open }) => useSavedThinking([a, b], open), { initialProps: { open: false } });
        expect(fetch).not.toHaveBeenCalled();
        rerender({ open: true });
        await waitFor(() => expect(result.current.text(b)).toBe('Second'));
        expect(fetch).toHaveBeenCalledTimes(1);
        expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ event_ids: ['event-a', 'event-b'] });
        rerender({ open: false });
        rerender({ open: true });
        expect(result.current.text(a)).toBe('First');
        expect(fetch).toHaveBeenCalledTimes(1);
    });

    it('reports failures and retries the requested entries', async () => {
        const fetch = vi.fn().mockResolvedValueOnce({ ok: false }).mockResolvedValueOnce({ ok: true, json: async () => ({ 'event-a': 'Recovered' }) });
        vi.stubGlobal('fetch', fetch);
        const { result } = renderHook(() => useSavedThinking([a], true));
        await waitFor(() => expect(result.current.error).toBe(true));
        act(() => result.current.retry());
        await waitFor(() => expect(result.current.text(a)).toBe('Recovered'));
        expect(result.current.error).toBe(false);
    });

    it('aborts a previous conversation and ignores its late response', async () => {
        let resolveOld;
        const fetch = vi.fn().mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
            .mockResolvedValueOnce({ ok: true, json: async () => ({ 'event-b': 'Current' }) });
        vi.stubGlobal('fetch', fetch);
        const { result, rerender, unmount } = renderHook(({ ref }) => useSavedThinking([ref], true), { initialProps: { ref: a } });
        rerender({ ref: b });
        expect(fetch.mock.calls[0][1].signal.aborted).toBe(true);
        await waitFor(() => expect(result.current.text(b)).toBe('Current'));
        await act(async () => resolveOld({ ok: true, json: async () => ({ 'event-a': 'Obsolete' }) }));
        expect(result.current.text(b)).toBe('Current');
        expect(result.current.text(a)).toBe('');
        unmount();
        expect(fetch.mock.calls[1][1].signal.aborted).toBe(true);
    });
});
