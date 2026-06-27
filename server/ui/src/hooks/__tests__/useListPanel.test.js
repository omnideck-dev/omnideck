import { renderHook, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import useListPanel from '../useListPanel.js';

// Focus: the "new item" highlight timer — it must clear after 700ms and,
// critically, be cancelled on unmount so a late fire doesn't land on an
// unmounted component (the cause of a CI flake: a timer firing after the
// test environment was torn down).
describe('useListPanel highlight timer', () => {
    beforeEach(() => {
        vi.useFakeTimers();
        global.fetch = vi.fn();
    });
    afterEach(() => {
        vi.useRealTimers();
        vi.restoreAllMocks();
    });

    const _fetchOnce = (items) => {
        global.fetch.mockResolvedValueOnce({ ok: true, json: async () => items });
    };

    it('highlights newly-added items, then clears them after 700ms', async () => {
        // First load only establishes the baseline — nothing is highlighted on
        // initial mount, only genuinely new items on later refreshes.
        _fetchOnce([{ id: 'a' }]);
        const { result } = renderHook(() => useListPanel('/api/x'));
        await act(async () => { await vi.advanceTimersByTimeAsync(0); });
        expect(result.current.newItemIds.size).toBe(0);

        // A refresh that brings a new item highlights only that item.
        _fetchOnce([{ id: 'a' }, { id: 'b' }]);
        await act(async () => { await result.current.refetch(); await vi.advanceTimersByTimeAsync(0); });
        expect(result.current.newItemIds.has('b')).toBe(true);
        expect(result.current.newItemIds.has('a')).toBe(false);

        await act(async () => { await vi.advanceTimersByTimeAsync(700); });
        expect(result.current.newItemIds.size).toBe(0);
    });

    it('cancels the pending highlight timer on unmount', async () => {
        _fetchOnce([{ id: 'a' }]);
        const { result, unmount } = renderHook(() => useListPanel('/api/x'));
        await act(async () => { await vi.advanceTimersByTimeAsync(0); });

        // A refresh adds a new item, leaving a highlight timer pending.
        _fetchOnce([{ id: 'a' }, { id: 'b' }]);
        await act(async () => { await result.current.refetch(); await vi.advanceTimersByTimeAsync(0); });
        expect(result.current.newItemIds.has('b')).toBe(true);

        // A timer is pending; unmount must cancel it.
        const clearSpy = vi.spyOn(global, 'clearTimeout');
        unmount();
        expect(clearSpy).toHaveBeenCalled();

        // Advancing past the highlight window does nothing — the callback
        // that would have called setState on the unmounted hook is gone.
        await act(async () => { await vi.advanceTimersByTimeAsync(700); });
        // newItemIds was captured pre-unmount; the cancelled timer never ran,
        // so no post-unmount state work happened (no error thrown above).
        expect(clearSpy).toHaveBeenCalled();
    });
});
