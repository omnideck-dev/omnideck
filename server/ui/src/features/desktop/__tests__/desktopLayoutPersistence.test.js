import {
    beforeEach,
    describe,
    expect,
    it,
} from 'vitest';

import {
    DESKTOP_LAYOUT_STORAGE_KEY,
    loadDesktopLayoutSnapshot,
    saveDesktopLayoutSnapshot,
} from '../desktopLayoutPersistence.js';

const CHAT = {
    id: 'destination:conversation',
    type: 'conversation',
    label: 'Chat',
    icon: 'bi-chat',
    navigationTarget: {
        kind: 'network',
        conversationId: 'conversation-1',
        agentId: 'agent-2',
    },
    closable: true,
};
const APP = {
    id: 'custom-app:text-lab',
    type: 'custom-app',
    label: 'Text Lab',
    icon: 'bi-fonts',
    navigationTarget: {
        kind: 'custom-app',
        appSlug: 'text-lab',
    },
    app: {
        slug: 'text-lab',
        title: 'Text Lab',
    },
    closable: true,
};
const SETTINGS = {
    id: 'destination:settings',
    type: 'settings',
    label: 'Settings',
    icon: 'bi-gear',
    navigationTarget: { kind: 'settings', tab: null },
    closable: true,
};

function model() {
    return {
        tabGroups: {
            left: {
                viewIds: [CHAT.id],
                activeViewId: CHAT.id,
            },
            right: {
                viewIds: [APP.id],
                activeViewId: APP.id,
            },
        },
        openViewsById: {
            [CHAT.id]: CHAT,
            [APP.id]: APP,
        },
        floatingViews: [],
        focusedFloatingViewId: null,
        focusedTabGroupId: 'right',
        splitRatio: 62,
        fullscreenViewId: APP.id,
    };
}

describe('desktop layout persistence', () => {
    beforeEach(() => {
        localStorage.removeItem(DESKTOP_LAYOUT_STORAGE_KEY);
    });

    it('restores tab order, placement, selection, split, and fullscreen', () => {
        saveDesktopLayoutSnapshot(model());

        const restored = loadDesktopLayoutSnapshot();
        const saved = JSON.parse(
            localStorage.getItem(DESKTOP_LAYOUT_STORAGE_KEY),
        );

        expect(saved.version).toBe(3);
        expect(saved).not.toHaveProperty('navigationTarget');
        expect(restored.layoutState.tabGroups.left.viewIds).toEqual([CHAT.id]);
        expect(restored.layoutState.tabGroups.right.viewIds).toEqual([APP.id]);
        expect(restored.layoutState.tabGroups.right.activeViewId).toBe(APP.id);
        expect(restored.layoutState.focusedTabGroupId).toBe('right');
        expect(restored.layoutState.splitRatio).toBe(62);
        expect(restored.layoutState.fullscreenViewId).toBe(APP.id);
        expect(restored.layoutState.openViewsById[APP.id]).toEqual(APP);
    });

    it('ignores corrupt snapshots without changing storage consumers', () => {
        localStorage.setItem(DESKTOP_LAYOUT_STORAGE_KEY, '{not-json');
        expect(loadDesktopLayoutSnapshot()).toBeNull();

        localStorage.setItem(DESKTOP_LAYOUT_STORAGE_KEY, JSON.stringify({
            version: 999,
        }));
        expect(loadDesktopLayoutSnapshot()).toBeNull();
    });

    it('migrates v2 by trusting focused View location, not saved navigation', () => {
        saveDesktopLayoutSnapshot(model());
        const previous = JSON.parse(
            localStorage.getItem(DESKTOP_LAYOUT_STORAGE_KEY),
        );
        previous.version = 2;
        // Deliberately conflicts with the focused right-hand Custom App.
        previous.navigationTarget = { kind: 'settings', tab: null };
        localStorage.setItem(
            DESKTOP_LAYOUT_STORAGE_KEY,
            JSON.stringify(previous),
        );

        const restored = loadDesktopLayoutSnapshot();
        const focusedTabGroup = restored.layoutState.tabGroups[
            restored.layoutState.focusedTabGroupId
        ];
        const focusedView = restored.layoutState.openViewsById[
            focusedTabGroup.activeViewId
        ];

        expect(restored).not.toHaveProperty('navigationTarget');
        expect(focusedView.id).toBe(APP.id);
        expect(focusedView.navigationTarget).toEqual({
            kind: 'custom-app',
            appSlug: 'text-lab',
        });
    });

    it('drops invalid and duplicate view placement while preserving an empty tabGroup', () => {
        localStorage.setItem(DESKTOP_LAYOUT_STORAGE_KEY, JSON.stringify({
            version: 2,
            layout: {
                tabGroups: {
                    left: {
                        viewIds: [CHAT.id, 'broken'],
                        activeViewId: 'broken',
                    },
                    right: {
                        viewIds: [CHAT.id],
                        activeViewId: CHAT.id,
                    },
                },
                views: [
                    CHAT,
                    { id: 'broken', type: 'unknown', label: 'Broken' },
                ],
                focusedTabGroupId: 'right',
                splitRatio: 200,
                fullscreenViewId: 'broken',
            },
        }));

        const restored = loadDesktopLayoutSnapshot().layoutState;
        expect(restored.tabGroups.left).toEqual({
            viewIds: [CHAT.id],
            activeViewId: CHAT.id,
        });
        expect(restored.tabGroups.right).toEqual({
            viewIds: [],
            activeViewId: null,
        });
        expect(restored.focusedTabGroupId).toBe('left');
        expect(restored.splitRatio).toBe(90);
        expect(restored.fullscreenViewId).toBeNull();
    });

    it('migrates the legacy window, pane, and surface vocabulary in place', () => {
        localStorage.setItem(DESKTOP_LAYOUT_STORAGE_KEY, JSON.stringify({
            version: 1,
            window: {
                panes: {
                    left: {
                        surfaceIds: ['destination:conversation'],
                        activeSurfaceId: 'destination:conversation',
                    },
                    right: {
                        surfaceIds: [
                            'conversation-execution:conversation-1:root:browser',
                        ],
                        activeSurfaceId:
                            'conversation-execution:conversation-1:root:browser',
                    },
                },
                surfaces: [
                    {
                        ...CHAT,
                        type: undefined,
                        navigationTarget: undefined,
                        kind: 'conversation',
                        group: 'destination',
                        destination: CHAT.navigationTarget,
                    },
                    {
                        id: 'conversation-execution:conversation-1:root:browser',
                        kind: 'conversation-execution',
                        group: 'conversation-execution',
                        label: 'Browser',
                        conversationId: 'conversation-1',
                        agentId: 'root-1',
                        resourceId: 'browser',
                        closable: true,
                    },
                ],
                floatingWindows: [],
                focusedPaneId: 'right',
                focusedFloatingSurfaceId: null,
                splitRatio: 55,
                fullscreenSurfaceId: null,
            },
            navigationDestination: {
                kind: 'chat',
                conversationId: 'conversation-1',
            },
        }));

        const restored = loadDesktopLayoutSnapshot();
        const browserId = 'workspace-resource:conversation-1:root:browser';

        expect(restored.layoutState.tabGroups.right.viewIds)
            .toEqual([browserId]);
        expect(restored.layoutState.openViewsById[browserId].type)
            .toBe('workspace-resource');
        expect(
            restored.layoutState.openViewsById[CHAT.id].navigationTarget,
        ).toEqual({
            kind: 'network',
            conversationId: 'conversation-1',
            agentId: 'agent-2',
        });
    });

    it('collapses formerly scoped Artifacts tabs into one library View', () => {
        const scopedId = 'destination:artifacts:conversation-2';
        const scopedArtifacts = {
            id: scopedId,
            type: 'artifacts',
            label: 'Conversation artifacts',
            icon: 'bi-collection',
            navigationTarget: {
                kind: 'artifacts',
                conversationId: 'conversation-2',
            },
            closable: true,
        };
        localStorage.setItem(DESKTOP_LAYOUT_STORAGE_KEY, JSON.stringify({
            version: 2,
            layout: {
                tabGroups: {
                    left: {
                        viewIds: [scopedId],
                        activeViewId: scopedId,
                    },
                    right: {
                        viewIds: [],
                        activeViewId: null,
                    },
                },
                views: [scopedArtifacts],
                focusedTabGroupId: 'left',
                floatingViews: [],
            },
            navigationTarget: scopedArtifacts.navigationTarget,
        }));

        const restored = loadDesktopLayoutSnapshot();
        expect(restored.layoutState.tabGroups.left.viewIds)
            .toEqual(['destination:artifacts']);
        expect(restored.layoutState.openViewsById['destination:artifacts'])
            .toMatchObject({
                id: 'destination:artifacts',
                navigationTarget: {
                    kind: 'artifacts',
                    conversationId: 'conversation-2',
                },
            });
    });

    it('restores floating view placement, bounds, focus, and stacking', () => {
        const desktop = model();
        desktop.openViewsById[SETTINGS.id] = SETTINGS;
        desktop.floatingViews = [{
            viewId: SETTINGS.id,
            x: 104,
            y: 72,
            width: 840,
            height: 540,
            zIndex: 4,
        }];
        desktop.focusedFloatingViewId = SETTINGS.id;
        saveDesktopLayoutSnapshot(
            desktop,
        );

        const restored = loadDesktopLayoutSnapshot().layoutState;
        expect(restored.floatingByViewId[SETTINGS.id]).toEqual({
            viewId: SETTINGS.id,
            x: 104,
            y: 72,
            width: 840,
            height: 540,
            zIndex: 4,
        });
        expect(restored.focusedFloatingViewId).toBe(SETTINGS.id);
        expect(restored.floatingZCounter).toBe(4);
        expect(restored.openViewsById[SETTINGS.id]).toEqual(SETTINGS);
    });
});
