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
    useCustomAppDesktopViews();
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
    });

    it('holds a slug until the Custom App catalog can resolve it', async () => {
        const { result, rerender } = renderHook(useHarness, { wrapper });

        act(() => result.current({
            type: APP_EFFECT_TYPES.OPEN_CUSTOM_APP_REQUESTED,
            appSlug: 'text-lab',
        }));
        expect(desktop.commands.openView).not.toHaveBeenCalled();

        customApps.catalog.loaded = true;
        rerender();

        await waitFor(() => expect(desktop.commands.openView)
            .toHaveBeenCalledWith(
                expect.objectContaining({
                    id: 'custom-app:text-lab',
                    resourceId: 'text-lab',
                }),
                { tabGroupId: 'left' },
            ));
    });
});
