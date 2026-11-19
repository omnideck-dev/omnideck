import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PROVIDER_CATALOG, PROVIDER_CATALOG_WITHOUT_APERTURE } from '../../__tests__/providerCatalogFixture.js';
import useProviderCatalog from '../useProviderCatalog.js';

afterEach(() => {
    vi.restoreAllMocks();
});

test('loads the catalog in server order and refresh picks up a newly listed kind', async () => {
    let entries = PROVIDER_CATALOG_WITHOUT_APERTURE;
    globalThis.fetch = vi.fn((url) => {
        expect(url).toBe('/api/providers/catalog');
        return Promise.resolve({ ok: true, json: async () => ({ providers: entries }) });
    });

    const { result } = renderHook(() => useProviderCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.catalog.map((c) => c.name)).toEqual([
        'ollama', 'openai_compat', 'anthropic', 'openai', 'openrouter',
    ]);

    entries = PROVIDER_CATALOG;
    await act(async () => {
        await result.current.refresh();
    });

    expect(result.current.catalog.map((c) => c.name)).toEqual([
        'ollama', 'aperture', 'openai_compat', 'anthropic', 'openai', 'openrouter',
    ]);
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
});

test('a failed refresh keeps the last catalog and reports the error', async () => {
    let succeeds = true;
    globalThis.fetch = vi.fn(() => Promise.resolve(succeeds
        ? { ok: true, json: async () => ({ providers: PROVIDER_CATALOG }) }
        : { ok: false, status: 500, json: async () => ({ error: 'Catalog unavailable' }) }));

    const { result } = renderHook(() => useProviderCatalog());
    await waitFor(() => expect(result.current.catalog).toEqual(PROVIDER_CATALOG));

    succeeds = false;
    await act(async () => {
        await result.current.refresh();
    });

    expect(result.current.catalog).toEqual(PROVIDER_CATALOG);
    expect(result.current.error).toBe('Catalog unavailable');
});
