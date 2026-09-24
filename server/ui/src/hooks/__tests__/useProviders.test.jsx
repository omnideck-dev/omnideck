import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import useProviders from '../useProviders.js';

afterEach(() => {
    vi.restoreAllMocks();
});

test('refresh replaces the shared provider catalog with current server data', async () => {
    let records = [{ name: 'ollama' }];
    globalThis.fetch = vi.fn(() => Promise.resolve({
        ok: true,
        json: async () => ({ providers: records }),
    }));

    const { result } = renderHook(() => useProviders());
    await waitFor(() => expect(result.current.providers).toEqual([{ name: 'ollama' }]));

    records = [{ name: 'ollama' }, { name: 'openai' }];
    await act(async () => {
        await result.current.refresh();
    });

    expect(result.current.providers).toEqual([
        { name: 'ollama' },
        { name: 'openai' },
    ]);
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
});

test('a failed refresh preserves the last usable catalog', async () => {
    let succeeds = true;
    globalThis.fetch = vi.fn(() => Promise.resolve(succeeds
        ? {
            ok: true,
            json: async () => ({ providers: [{ name: 'anthropic' }] }),
        }
        : {
            ok: false,
            status: 503,
            json: async () => ({ error: 'Provider service unavailable' }),
        }));

    const { result } = renderHook(() => useProviders());
    await waitFor(() => expect(result.current.providers).toEqual([{ name: 'anthropic' }]));

    succeeds = false;
    await act(async () => {
        await result.current.refresh();
    });

    expect(result.current.providers).toEqual([{ name: 'anthropic' }]);
    expect(result.current.error).toBe('Provider service unavailable');
});
