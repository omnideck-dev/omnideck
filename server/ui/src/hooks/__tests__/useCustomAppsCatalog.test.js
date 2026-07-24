import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import useCustomAppsCatalog from '../useCustomAppsCatalog.js';

const APP = { slug: 'text-lab', title: 'Text Lab', icon: 'bi-fonts' };

afterEach(() => vi.restoreAllMocks());

test('discovers apps and synchronizes the persisted Home selection', async () => {
    global.fetch = vi.fn(() => Promise.resolve({
        ok: true,
        json: async () => ({ apps: [APP], home_app_slug: 'text-lab' }),
    }));
    const onHomeAppChange = vi.fn();
    const { result } = renderHook(() => useCustomAppsCatalog({
        enabled: true,
        homeAppSlug: null,
        onHomeAppChange,
    }));

    await act(async () => result.current.refresh());

    expect(result.current.apps).toEqual([APP]);
    expect(result.current.findBySlug('text-lab')).toEqual(APP);
    expect(onHomeAppChange).toHaveBeenCalledWith('text-lab');
});

test('clears catalog state when the feature is disabled', async () => {
    global.fetch = vi.fn(() => Promise.resolve({
        ok: true,
        json: async () => ({ apps: [APP], home_app_slug: null }),
    }));
    const props = { enabled: true };
    const { result, rerender } = renderHook(() => useCustomAppsCatalog({
        enabled: props.enabled,
        homeAppSlug: null,
        onHomeAppChange: vi.fn(),
    }));
    await act(async () => result.current.refresh());
    expect(result.current.loaded).toBe(true);

    props.enabled = false;
    rerender();
    await waitFor(() => expect(result.current.loaded).toBe(false));
    expect(result.current.apps).toEqual([]);
});
