import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const APP = { slug: 'text-lab', title: 'Text Lab', icon: 'bi-fonts' };
const harness = vi.hoisted(() => ({
    enabled: true,
    homeAppSlug: null,
    setHomeAppSlug: vi.fn(),
    catalog: {
        apps: [],
        loaded: true,
        loading: false,
        error: '',
        refresh: vi.fn(),
        findBySlug: vi.fn(),
    },
}));

vi.mock('../../../contexts/AppData.jsx', () => ({
    useAppData: () => ({ features: { custom_apps: harness.enabled } }),
}));

vi.mock('../../app/AppSettings.jsx', () => ({
    useAppSettings: () => ({
        homeAppSlug: harness.homeAppSlug,
        setHomeAppSlug: harness.setHomeAppSlug,
    }),
}));

vi.mock('../useCustomAppsCatalog.js', () => ({
    default: () => harness.catalog,
}));

const { CustomAppsProvider, useCustomApps } = await import('../CustomApps.jsx');

function wrapper({ children }) {
    return <CustomAppsProvider>{children}</CustomAppsProvider>;
}

describe('CustomAppsProvider', () => {
    beforeEach(() => {
        harness.enabled = true;
        harness.homeAppSlug = null;
        harness.setHomeAppSlug.mockReset();
        harness.catalog.refresh.mockReset();
    });

    afterEach(() => vi.restoreAllMocks());

    it('owns the open Custom App and iframe reload identity', () => {
        const { result } = renderHook(useCustomApps, { wrapper });

        act(() => result.current.open(APP));
        expect(result.current.openApp).toEqual(APP);

        act(() => result.current.reload());
        expect(result.current.reloadSignal).toBe(1);

        act(() => result.current.open(APP));
        expect(result.current.reloadSignal).toBe(1);

        act(() => result.current.close());
        expect(result.current.openApp).toBeNull();
    });

    it('persists Home assignment without presentation state', async () => {
        globalThis.fetch = vi.fn(() => Promise.resolve({
            ok: true,
            json: async () => ({ home_app_slug: 'text-lab' }),
        }));
        const { result } = renderHook(useCustomApps, { wrapper });
        act(() => result.current.open(APP));

        await act(async () => result.current.toggleHome());

        expect(globalThis.fetch).toHaveBeenCalledWith('/api/custom-apps/home', expect.objectContaining({
            method: 'PUT',
        }));
        expect(harness.setHomeAppSlug).toHaveBeenCalledWith('text-lab');
    });

    it('closes the open Custom App when the feature is disabled', () => {
        const { result, rerender } = renderHook(useCustomApps, { wrapper });
        act(() => result.current.open(APP));
        expect(result.current.openApp).toEqual(APP);

        harness.enabled = false;
        rerender();

        expect(result.current.openApp).toBeNull();
    });
});
