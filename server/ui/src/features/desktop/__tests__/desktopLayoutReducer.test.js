import { describe, expect, it } from 'vitest';
import {
    createInitialDesktopLayoutState,
    DESKTOP_TAB_GROUP_IDS,
    desktopLayoutReducer,
} from '../desktopLayoutReducer.js';

const CHAT = { id: 'destination:conversation', type: 'conversation' };
const APP = { id: 'custom-app:text-lab', type: 'custom-app' };
const TERMINAL = {
    id: 'workspace-resource:conversation-1:root:terminal',
    type: 'workspace-resource',
};

function reduce(actions, initial = createInitialDesktopLayoutState(CHAT)) {
    return actions.reduce(desktopLayoutReducer, initial);
}

describe('desktopLayoutReducer', () => {
    it('uses the same open, select, and move operations for both tabGroups', () => {
        const state = reduce([
            {
                type: 'OPEN_VIEW',
                view: APP,
                tabGroupId: DESKTOP_TAB_GROUP_IDS.RIGHT,
            },
            {
                type: 'OPEN_VIEW',
                view: TERMINAL,
                tabGroupId: DESKTOP_TAB_GROUP_IDS.RIGHT,
            },
            {
                type: 'SELECT_VIEW',
                tabGroupId: DESKTOP_TAB_GROUP_IDS.RIGHT,
                viewId: APP.id,
            },
            {
                type: 'MOVE_VIEW',
                tabGroupId: DESKTOP_TAB_GROUP_IDS.LEFT,
                viewId: APP.id,
            },
        ]);

        expect(state.tabGroups.left.viewIds).toEqual([CHAT.id, APP.id]);
        expect(state.tabGroups.left.activeViewId).toBe(APP.id);
        expect(state.tabGroups.right.viewIds).toEqual([TERMINAL.id]);
        expect(state.tabGroups.right.activeViewId).toBe(TERMINAL.id);
    });

    it('keeps registered views mounted when they are inactive', () => {
        const state = reduce([
            {
                type: 'OPEN_VIEW',
                view: APP,
                tabGroupId: DESKTOP_TAB_GROUP_IDS.LEFT,
            },
            {
                type: 'SELECT_VIEW',
                tabGroupId: DESKTOP_TAB_GROUP_IDS.LEFT,
                viewId: CHAT.id,
            },
        ]);

        expect(state.openViewsById[APP.id]).toEqual(APP);
        expect(state.tabGroups.left.activeViewId).toBe(CHAT.id);
    });

    it('activates an existing view without reordering its tabGroup', () => {
        const state = reduce([
            {
                type: 'OPEN_VIEW',
                view: APP,
                tabGroupId: DESKTOP_TAB_GROUP_IDS.LEFT,
            },
            {
                type: 'OPEN_VIEW',
                view: CHAT,
                tabGroupId: DESKTOP_TAB_GROUP_IDS.LEFT,
            },
        ]);

        expect(state.tabGroups.left.viewIds).toEqual([CHAT.id, APP.id]);
        expect(state.tabGroups.left.activeViewId).toBe(CHAT.id);
    });

    it('syncs explicitly selected views without relying on view groups', () => {
        const placed = reduce([
            {
                type: 'OPEN_VIEW',
                view: TERMINAL,
                tabGroupId: DESKTOP_TAB_GROUP_IDS.LEFT,
            },
            {
                type: 'OPEN_VIEW',
                view: APP,
                tabGroupId: DESKTOP_TAB_GROUP_IDS.RIGHT,
            },
        ]);
        const next = desktopLayoutReducer(placed, {
            type: 'SYNC_VIEWS',
            views: [
                {
                    ...TERMINAL,
                    label: 'Terminal',
                },
            ],
            closeViewIds: [APP.id],
        });

        expect(next.tabGroups.left.viewIds).toContain(TERMINAL.id);
        expect(next.openViewsById[TERMINAL.id].label).toBe('Terminal');
        expect(next.openViewsById[APP.id]).toBeUndefined();
        expect(next.tabGroups.right.viewIds).not.toContain(APP.id);
    });

    it('selects an existing view without moving it back to the requested tabGroup', () => {
        const placed = reduce([
            {
                type: 'OPEN_VIEW',
                view: APP,
                tabGroupId: DESKTOP_TAB_GROUP_IDS.RIGHT,
            },
        ]);
        const reopened = desktopLayoutReducer(placed, {
            type: 'OPEN_VIEW',
            view: { ...APP, label: 'Updated Text Lab' },
            tabGroupId: DESKTOP_TAB_GROUP_IDS.LEFT,
        });

        expect(reopened.tabGroups.right.viewIds).toContain(APP.id);
        expect(reopened.tabGroups.right.activeViewId).toBe(APP.id);
        expect(reopened.tabGroups.left.viewIds).not.toContain(APP.id);
        expect(reopened.openViewsById[APP.id].label).toBe('Updated Text Lab');
    });

    it('closes a view and selects an adjacent tab in the same tabGroup', () => {
        const state = reduce([
            {
                type: 'OPEN_VIEW',
                view: APP,
                tabGroupId: DESKTOP_TAB_GROUP_IDS.LEFT,
            },
            {
                type: 'CLOSE_VIEW',
                viewId: APP.id,
            },
        ]);

        expect(state.tabGroups.left.activeViewId).toBe(CHAT.id);
        expect(state.openViewsById[APP.id]).toBeUndefined();
    });

    it('owns the draggable horizontal split ratio', () => {
        const state = desktopLayoutReducer(
            createInitialDesktopLayoutState(),
            { type: 'SET_SPLIT_RATIO', ratio: 63 },
        );
        expect(state.splitRatio).toBe(63);
    });

    it('shows one registered view full screen and restores when it closes', () => {
        const fullscreen = reduce([
            {
                type: 'OPEN_VIEW',
                view: APP,
                tabGroupId: DESKTOP_TAB_GROUP_IDS.RIGHT,
            },
            { type: 'SET_FULLSCREEN_VIEW', viewId: APP.id },
        ]);
        const closed = desktopLayoutReducer(fullscreen, {
            type: 'CLOSE_VIEW',
            viewId: APP.id,
        });

        expect(fullscreen.fullscreenViewId).toBe(APP.id);
        expect(closed.fullscreenViewId).toBeNull();
    });

    it('activates an inactive view when it enters full screen', () => {
        const state = reduce([
            {
                type: 'OPEN_VIEW',
                view: APP,
                tabGroupId: DESKTOP_TAB_GROUP_IDS.LEFT,
            },
            {
                type: 'SELECT_VIEW',
                tabGroupId: DESKTOP_TAB_GROUP_IDS.LEFT,
                viewId: CHAT.id,
            },
            {
                type: 'ENTER_FULLSCREEN',
                viewId: APP.id,
            },
        ]);

        expect(state.tabGroups.left.activeViewId).toBe(APP.id);
        expect(state.focusedTabGroupId).toBe(DESKTOP_TAB_GROUP_IDS.LEFT);
        expect(state.fullscreenViewId).toBe(APP.id);
    });

    it('floats one view without recreating it and docks it back into either tabGroup', () => {
        const placed = reduce([
            {
                type: 'OPEN_VIEW',
                view: APP,
                tabGroupId: DESKTOP_TAB_GROUP_IDS.RIGHT,
            },
        ]);
        const registeredApp = placed.openViewsById[APP.id];
        const floating = desktopLayoutReducer(placed, {
            type: 'FLOAT_VIEW',
            viewId: APP.id,
            bounds: {
                x: 90,
                y: 70,
                width: 640,
                height: 420,
            },
        });

        expect(floating.tabGroups.right.viewIds).not.toContain(APP.id);
        expect(floating.floatingByViewId[APP.id]).toMatchObject({
            x: 90,
            y: 70,
            width: 640,
            height: 420,
        });
        expect(floating.focusedFloatingViewId).toBe(APP.id);
        expect(floating.openViewsById[APP.id]).toBe(registeredApp);

        const docked = desktopLayoutReducer(floating, {
            type: 'MOVE_VIEW',
            viewId: APP.id,
            tabGroupId: DESKTOP_TAB_GROUP_IDS.LEFT,
        });
        expect(docked.floatingByViewId[APP.id]).toBeUndefined();
        expect(docked.tabGroups.left.activeViewId).toBe(APP.id);
        expect(docked.openViewsById[APP.id]).toBe(registeredApp);
    });

    it('persists floating resize bounds and can enter full screen in place', () => {
        const floating = reduce([
            {
                type: 'OPEN_VIEW',
                view: APP,
                tabGroupId: DESKTOP_TAB_GROUP_IDS.RIGHT,
            },
            {
                type: 'FLOAT_VIEW',
                viewId: APP.id,
            },
            {
                type: 'UPDATE_FLOATING_BOUNDS',
                viewId: APP.id,
                bounds: { x: 120, y: 80, width: 880, height: 560 },
            },
            {
                type: 'ENTER_FULLSCREEN',
                viewId: APP.id,
            },
        ]);

        expect(floating.floatingByViewId[APP.id]).toMatchObject({
            x: 120,
            y: 80,
            width: 880,
            height: 560,
        });
        expect(floating.fullscreenViewId).toBe(APP.id);
    });

    it('normalizes floating stacking when focus changes', () => {
        const floating = reduce([
            {
                type: 'OPEN_VIEW',
                view: APP,
                tabGroupId: DESKTOP_TAB_GROUP_IDS.RIGHT,
            },
            {
                type: 'OPEN_VIEW',
                view: TERMINAL,
                tabGroupId: DESKTOP_TAB_GROUP_IDS.RIGHT,
            },
            { type: 'FLOAT_VIEW', viewId: APP.id },
            { type: 'FLOAT_VIEW', viewId: TERMINAL.id },
        ]);
        const inflated = {
            ...floating,
            floatingByViewId: {
                [APP.id]: {
                    ...floating.floatingByViewId[APP.id],
                    zIndex: 800,
                },
                [TERMINAL.id]: {
                    ...floating.floatingByViewId[TERMINAL.id],
                    zIndex: 900,
                },
            },
            floatingZCounter: 900,
        };

        const focused = desktopLayoutReducer(inflated, {
            type: 'FOCUS_FLOATING_VIEW',
            viewId: APP.id,
        });

        expect(focused.floatingByViewId[TERMINAL.id].zIndex).toBe(1);
        expect(focused.floatingByViewId[APP.id].zIndex).toBe(2);
        expect(focused.floatingZCounter).toBe(2);
    });
});
