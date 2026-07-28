import { act, renderHook } from '@testing-library/react';
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
        localStorage.clear();
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

    it('persists ordered, unique docked App slugs', () => {
        localStorage.setItem(
            'omnideck_sidebar_docked_apps',
            JSON.stringify(['text-lab']),
        );
        const { result } = renderHook(useCustomApps, { wrapper });

        expect(result.current.dockedAppSlugs).toEqual(['text-lab']);
        act(() => result.current.dockApp('notes-lab'));
        act(() => result.current.dockApp('text-lab'));
        expect(result.current.dockedAppSlugs).toEqual(['text-lab', 'notes-lab']);
        expect(JSON.parse(localStorage.getItem('omnideck_sidebar_docked_apps')))
            .toEqual(['text-lab', 'notes-lab']);

        act(() => result.current.reorderDockedApps(['notes-lab', 'text-lab']));
        expect(result.current.dockedAppSlugs).toEqual(['notes-lab', 'text-lab']);
        expect(JSON.parse(localStorage.getItem('omnideck_sidebar_docked_apps')))
            .toEqual(['notes-lab', 'text-lab']);

        act(() => result.current.undockApp('text-lab'));
        expect(result.current.dockedAppSlugs).toEqual(['notes-lab']);
        expect(JSON.parse(localStorage.getItem('omnideck_sidebar_docked_apps')))
            .toEqual(['notes-lab']);
    });
});
