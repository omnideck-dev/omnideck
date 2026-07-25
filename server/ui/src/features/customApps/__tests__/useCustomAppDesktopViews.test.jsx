import {
    act,
    renderHook,
    waitFor,
} from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
    AppEffectsProvider,
    useAppEffectDispatch,
} from '../../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../../app/appEffectTypes.js';
import useCustomAppDesktopViews from '../useCustomAppDesktopViews.js';

const APP = {
    slug: 'text-lab',
    title: 'Text Lab',
    icon: 'bi-fonts',
};
const customApps = vi.hoisted(() => ({
    enabled: true,
    featureLoaded: true,
    catalog: {
        loaded: false,
        findBySlug: vi.fn(),
    },
}));
const desktop = vi.hoisted(() => ({
    catalog: {
        openViews: [],
        openViewsById: {},
    },
    commands: {
        openView: vi.fn(),
        updateViews: vi.fn(),
        syncViews: vi.fn(),
        closeViews: vi.fn(),
    },
}));
const openApp = vi.hoisted(() => vi.fn());

vi.mock('../CustomApps.jsx', () => ({
    useCustomApps: () => customApps,
}));

vi.mock('../../desktop/DesktopViewRuntime.jsx', () => ({
    useDesktopViewCatalog: () => desktop.catalog,
    useDesktopViewCommands: () => desktop.commands,
}));

vi.mock('../../navigation/DesktopNavigation.jsx', () => ({
    useCurrentNavigationTarget: () => ({
        kind: 'chat',
        conversationId: 'conversation-1',
    }),
    useDesktopNavigationCommands: () => ({
        openChat: vi.fn(),
    }),
}));

const wrapper = ({ children }) => (
    <AppEffectsProvider>
        {children}
    </AppEffectsProvider>
);

function useHarness() {
    const dispatch = useAppEffectDispatch();
    useCustomAppDesktopViews({ openApp });
    return dispatch;
}

describe('useCustomAppDesktopViews deferred navigation', () => {
    beforeEach(() => {
        customApps.enabled = true;
        customApps.featureLoaded = true;
        customApps.catalog.loaded = false;
        customApps.catalog.findBySlug.mockReset();
        customApps.catalog.findBySlug.mockReturnValue(APP);
        desktop.catalog.openViews = [];
        desktop.catalog.openViewsById = {};
        Object.values(desktop.commands).forEach((command) => (
            command.mockReset()
        ));
        openApp.mockReset();
    });

    it('holds a slug until the Custom App catalog can resolve it', async () => {
        const { result, rerender } = renderHook(useHarness, { wrapper });

        act(() => result.current({
            type: APP_EFFECT_TYPES.OPEN_CUSTOM_APP_REQUESTED,
            appSlug: 'text-lab',
        }));
        expect(openApp).not.toHaveBeenCalled();

        customApps.catalog.loaded = true;
        rerender();

        await waitFor(() => expect(openApp)
            .toHaveBeenCalledWith(APP, 'left'));
    });

    it('rehydrates a restored View from the live catalog', async () => {
        customApps.catalog.loaded = true;
        desktop.catalog.openViews = [{
            id: 'custom-app:text-lab',
            type: 'custom-app',
            identity: { appSlug: 'text-lab' },
            label: 'Text Lab',
            icon: 'bi-fonts',
            closable: true,
        }];

        renderHook(useHarness, { wrapper });

        await waitFor(() => expect(desktop.commands.syncViews)
            .toHaveBeenCalledWith({
                views: [expect.objectContaining({
                    id: 'custom-app:text-lab',
                    identity: expect.objectContaining({
                        appSlug: 'text-lab',
                    }),
                    app: APP,
                    reloadSignal: 0,
                    actions: ['reload'],
                })],
                closeViewIds: [],
            }));
    });

    it('closes a restored View when its catalog entry is gone', async () => {
        customApps.catalog.loaded = true;
        customApps.catalog.findBySlug.mockReturnValue(null);
        desktop.catalog.openViews = [{
            id: 'custom-app:missing-app',
            type: 'custom-app',
            identity: { appSlug: 'missing-app' },
            label: 'Missing App',
            icon: 'bi-grid',
            closable: true,
        }];

        renderHook(useHarness, { wrapper });

        await waitFor(() => expect(desktop.commands.syncViews)
            .toHaveBeenCalledWith({
                views: [],
                closeViewIds: ['custom-app:missing-app'],
            }));
    });
});
