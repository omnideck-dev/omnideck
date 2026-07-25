import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const harness = vi.hoisted(() => ({
    enabled: true,
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
        harness.catalog.refresh.mockReset();
    });

    it('publishes the shared catalog without open-app presentation state', () => {
        const { result } = renderHook(useCustomApps, { wrapper });

        expect(result.current.enabled).toBe(true);
        expect(result.current.catalog).toBe(harness.catalog);
        expect(result.current.openApp).toBeUndefined();
        expect(harness.catalog.refresh).toHaveBeenCalledOnce();
    });

    it('reports feature availability without owning open Views', () => {
        const { result, rerender } = renderHook(useCustomApps, { wrapper });

        harness.enabled = false;
        rerender();

        expect(result.current.enabled).toBe(false);
        expect(result.current.catalog).toBe(harness.catalog);
    });
});
