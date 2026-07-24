import {
    beforeEach,
    describe,
    expect,
    it,
} from 'vitest';

import {
    DESKTOP_WINDOW_STORAGE_KEY,
    loadDesktopWindowSnapshot,
    saveDesktopWindowSnapshot,
} from '../desktopWindowPersistence.js';

const CHAT = {
    id: 'destination:conversation',
    kind: 'conversation',
    group: 'destination',
    label: 'Chat',
    icon: 'bi-chat',
    destination: {
        kind: 'network',
        conversationId: 'conversation-1',
        agentId: 'agent-2',
    },
    closable: true,
};
const APP = {
    id: 'custom-app:text-lab',
    kind: 'custom-app',
    group: 'custom-app',
    label: 'Text Lab',
    icon: 'bi-fonts',
    app: {
        slug: 'text-lab',
        title: 'Text Lab',
    },
    closable: true,
};
const SETTINGS = {
    id: 'destination:settings',
    kind: 'settings',
    group: 'destination',
    label: 'Settings',
    icon: 'bi-gear',
    destination: { kind: 'settings', tab: null },
    closable: true,
};

function model() {
    return {
        panes: {
            left: {
                surfaceIds: [CHAT.id],
                activeSurfaceId: CHAT.id,
            },
            right: {
                surfaceIds: [APP.id],
                activeSurfaceId: APP.id,
            },
        },
        surfacesById: {
            [CHAT.id]: CHAT,
            [APP.id]: APP,
        },
        focusedPaneId: 'right',
        splitRatio: 62,
        fullscreenSurfaceId: APP.id,
    };
}

describe('desktop window persistence', () => {
    beforeEach(() => {
        localStorage.removeItem(DESKTOP_WINDOW_STORAGE_KEY);
    });

    it('restores tab order, placement, selection, split, fullscreen, and navigation', () => {
        const navigationDestination = { kind: 'custom-app', appSlug: 'text-lab' };
        saveDesktopWindowSnapshot(model(), navigationDestination);

        const restored = loadDesktopWindowSnapshot();

        expect(restored.windowState.panes.left.surfaceIds).toEqual([CHAT.id]);
        expect(restored.windowState.panes.right.surfaceIds).toEqual([APP.id]);
        expect(restored.windowState.panes.right.activeSurfaceId).toBe(APP.id);
        expect(restored.windowState.focusedPaneId).toBe('right');
        expect(restored.windowState.splitRatio).toBe(62);
        expect(restored.windowState.fullscreenSurfaceId).toBe(APP.id);
        expect(restored.windowState.surfacesById[APP.id]).toEqual(APP);
        expect(restored.navigationDestination).toEqual(navigationDestination);
    });

    it('ignores corrupt snapshots without changing storage consumers', () => {
        localStorage.setItem(DESKTOP_WINDOW_STORAGE_KEY, '{not-json');
        expect(loadDesktopWindowSnapshot()).toBeNull();

        localStorage.setItem(DESKTOP_WINDOW_STORAGE_KEY, JSON.stringify({
            version: 999,
        }));
        expect(loadDesktopWindowSnapshot()).toBeNull();
    });

    it('drops invalid and duplicate surface placement while preserving an empty pane', () => {
        localStorage.setItem(DESKTOP_WINDOW_STORAGE_KEY, JSON.stringify({
            version: 1,
            window: {
                panes: {
                    left: {
                        surfaceIds: [CHAT.id, 'broken'],
                        activeSurfaceId: 'broken',
                    },
                    right: {
                        surfaceIds: [CHAT.id],
                        activeSurfaceId: CHAT.id,
                    },
                },
                surfaces: [
                    CHAT,
                    { id: 'broken', kind: 'unknown', label: 'Broken' },
                ],
                focusedPaneId: 'right',
                splitRatio: 200,
                fullscreenSurfaceId: 'broken',
            },
        }));

        const restored = loadDesktopWindowSnapshot().windowState;
        expect(restored.panes.left).toEqual({
            surfaceIds: [CHAT.id],
            activeSurfaceId: CHAT.id,
        });
        expect(restored.panes.right).toEqual({
            surfaceIds: [],
            activeSurfaceId: null,
        });
        expect(restored.focusedPaneId).toBe('left');
        expect(restored.splitRatio).toBe(90);
        expect(restored.fullscreenSurfaceId).toBeNull();
    });

    it('restores floating window placement, bounds, focus, and stacking', () => {
        const desktop = model();
        desktop.surfacesById[SETTINGS.id] = SETTINGS;
        desktop.floatingWindows = [{
            surfaceId: SETTINGS.id,
            x: 104,
            y: 72,
            width: 840,
            height: 540,
            zIndex: 4,
        }];
        desktop.focusedFloatingSurfaceId = SETTINGS.id;
        saveDesktopWindowSnapshot(
            desktop,
            SETTINGS.destination,
        );

        const restored = loadDesktopWindowSnapshot().windowState;
        expect(restored.floatingWindowsBySurfaceId[SETTINGS.id]).toEqual({
            surfaceId: SETTINGS.id,
            x: 104,
            y: 72,
            width: 840,
            height: 540,
            zIndex: 4,
        });
        expect(restored.focusedFloatingSurfaceId).toBe(SETTINGS.id);
        expect(restored.floatingZCounter).toBe(4);
        expect(restored.surfacesById[SETTINGS.id]).toEqual(SETTINGS);
    });
});
