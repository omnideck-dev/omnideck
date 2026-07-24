import { describe, expect, it } from 'vitest';
import {
    createInitialDesktopWindowState,
    DESKTOP_PANE_IDS,
    desktopWindowReducer,
} from '../desktopWindowReducer.js';

const CHAT = { id: 'destination:conversation', kind: 'conversation', group: 'destination' };
const APP = { id: 'custom-app:text-lab', kind: 'custom-app', group: 'custom-app' };
const TERMINAL = {
    id: 'conversation-execution:conversation-1:root:terminal',
    kind: 'conversation-execution',
    group: 'conversation-execution',
};

function reduce(actions, initial = createInitialDesktopWindowState(CHAT)) {
    return actions.reduce(desktopWindowReducer, initial);
}

describe('desktopWindowReducer', () => {
    it('uses the same open, select, and move operations for both panes', () => {
        const state = reduce([
            {
                type: 'OPEN_SURFACE',
                surface: APP,
                paneId: DESKTOP_PANE_IDS.RIGHT,
            },
            {
                type: 'OPEN_SURFACE',
                surface: TERMINAL,
                paneId: DESKTOP_PANE_IDS.RIGHT,
            },
            {
                type: 'SELECT_SURFACE',
                paneId: DESKTOP_PANE_IDS.RIGHT,
                surfaceId: APP.id,
            },
            {
                type: 'MOVE_SURFACE',
                paneId: DESKTOP_PANE_IDS.LEFT,
                surfaceId: APP.id,
            },
        ]);

        expect(state.panes.left.surfaceIds).toEqual([CHAT.id, APP.id]);
        expect(state.panes.left.activeSurfaceId).toBe(APP.id);
        expect(state.panes.right.surfaceIds).toEqual([TERMINAL.id]);
        expect(state.panes.right.activeSurfaceId).toBe(TERMINAL.id);
    });

    it('keeps registered surfaces mounted when they are inactive', () => {
        const state = reduce([
            {
                type: 'OPEN_SURFACE',
                surface: APP,
                paneId: DESKTOP_PANE_IDS.LEFT,
            },
            {
                type: 'SELECT_SURFACE',
                paneId: DESKTOP_PANE_IDS.LEFT,
                surfaceId: CHAT.id,
            },
        ]);

        expect(state.surfacesById[APP.id]).toEqual(APP);
        expect(state.panes.left.activeSurfaceId).toBe(CHAT.id);
    });

    it('activates an existing surface without reordering its pane', () => {
        const state = reduce([
            {
                type: 'OPEN_SURFACE',
                surface: APP,
                paneId: DESKTOP_PANE_IDS.LEFT,
            },
            {
                type: 'OPEN_SURFACE',
                surface: CHAT,
                paneId: DESKTOP_PANE_IDS.LEFT,
            },
        ]);

        expect(state.panes.left.surfaceIds).toEqual([CHAT.id, APP.id]);
        expect(state.panes.left.activeSurfaceId).toBe(CHAT.id);
    });

    it('reconciles feature-owned surface groups without changing existing placement', () => {
        const placed = reduce([
            {
                type: 'OPEN_SURFACE',
                surface: TERMINAL,
                paneId: DESKTOP_PANE_IDS.LEFT,
            },
        ]);
        const next = desktopWindowReducer(placed, {
            type: 'RECONCILE_SURFACE_GROUP',
            group: 'conversation-execution',
            surfaces: [
                TERMINAL,
                {
                    id: 'browser',
                    kind: 'conversation-execution',
                    group: 'conversation-execution',
                },
            ],
            defaultPaneId: DESKTOP_PANE_IDS.RIGHT,
        });

        expect(next.panes.left.surfaceIds).toContain(TERMINAL.id);
        expect(next.panes.right.surfaceIds).toContain('browser');
    });

    it('waits to focus a surface until its feature registers it', () => {
        const pending = reduce([
            {
                type: 'REQUEST_SURFACE_FOCUS',
                surfaceId: 'file:/tmp/report.md',
                paneId: DESKTOP_PANE_IDS.RIGHT,
            },
        ]);
        const restored = desktopWindowReducer(pending, {
            type: 'REGISTER_SURFACES',
            surfaces: [{
                id: 'file:/tmp/report.md',
                kind: 'artifact-file',
                group: 'artifact-file',
            }],
        });

        expect(pending.pendingFocus.surfaceId).toBe('file:/tmp/report.md');
        expect(restored.panes.right.activeSurfaceId).toBe('file:/tmp/report.md');
        expect(restored.pendingFocus).toBeNull();
    });

    it('selects an existing surface without moving it back to the requested pane', () => {
        const placed = reduce([
            {
                type: 'OPEN_SURFACE',
                surface: APP,
                paneId: DESKTOP_PANE_IDS.RIGHT,
            },
        ]);
        const reopened = desktopWindowReducer(placed, {
            type: 'OPEN_SURFACE',
            surface: { ...APP, label: 'Updated Text Lab' },
            paneId: DESKTOP_PANE_IDS.LEFT,
        });

        expect(reopened.panes.right.surfaceIds).toContain(APP.id);
        expect(reopened.panes.right.activeSurfaceId).toBe(APP.id);
        expect(reopened.panes.left.surfaceIds).not.toContain(APP.id);
        expect(reopened.surfacesById[APP.id].label).toBe('Updated Text Lab');
    });

    it('closes a surface and selects an adjacent tab in the same pane', () => {
        const state = reduce([
            {
                type: 'OPEN_SURFACE',
                surface: APP,
                paneId: DESKTOP_PANE_IDS.LEFT,
            },
            {
                type: 'CLOSE_SURFACE',
                surfaceId: APP.id,
            },
        ]);

        expect(state.panes.left.activeSurfaceId).toBe(CHAT.id);
        expect(state.surfacesById[APP.id]).toBeUndefined();
    });

    it('owns the draggable horizontal split ratio', () => {
        const state = desktopWindowReducer(
            createInitialDesktopWindowState(),
            { type: 'SET_SPLIT_RATIO', ratio: 63 },
        );
        expect(state.splitRatio).toBe(63);
    });

    it('shows one registered surface full screen and restores when it closes', () => {
        const fullscreen = reduce([
            {
                type: 'OPEN_SURFACE',
                surface: APP,
                paneId: DESKTOP_PANE_IDS.RIGHT,
            },
            { type: 'SET_FULLSCREEN_SURFACE', surfaceId: APP.id },
        ]);
        const closed = desktopWindowReducer(fullscreen, {
            type: 'CLOSE_SURFACE',
            surfaceId: APP.id,
        });

        expect(fullscreen.fullscreenSurfaceId).toBe(APP.id);
        expect(closed.fullscreenSurfaceId).toBeNull();
    });

    it('activates an inactive surface when it enters full screen', () => {
        const state = reduce([
            {
                type: 'OPEN_SURFACE',
                surface: APP,
                paneId: DESKTOP_PANE_IDS.LEFT,
            },
            {
                type: 'SELECT_SURFACE',
                paneId: DESKTOP_PANE_IDS.LEFT,
                surfaceId: CHAT.id,
            },
            {
                type: 'ENTER_FULLSCREEN',
                surfaceId: APP.id,
            },
        ]);

        expect(state.panes.left.activeSurfaceId).toBe(APP.id);
        expect(state.focusedPaneId).toBe(DESKTOP_PANE_IDS.LEFT);
        expect(state.fullscreenSurfaceId).toBe(APP.id);
    });

    it('floats one surface without recreating it and docks it back into either pane', () => {
        const placed = reduce([
            {
                type: 'OPEN_SURFACE',
                surface: APP,
                paneId: DESKTOP_PANE_IDS.RIGHT,
            },
        ]);
        const registeredApp = placed.surfacesById[APP.id];
        const floating = desktopWindowReducer(placed, {
            type: 'FLOAT_SURFACE',
            surfaceId: APP.id,
            bounds: {
                x: 90,
                y: 70,
                width: 640,
                height: 420,
            },
        });

        expect(floating.panes.right.surfaceIds).not.toContain(APP.id);
        expect(floating.floatingWindowsBySurfaceId[APP.id]).toMatchObject({
            x: 90,
            y: 70,
            width: 640,
            height: 420,
        });
        expect(floating.focusedFloatingSurfaceId).toBe(APP.id);
        expect(floating.surfacesById[APP.id]).toBe(registeredApp);

        const docked = desktopWindowReducer(floating, {
            type: 'MOVE_SURFACE',
            surfaceId: APP.id,
            paneId: DESKTOP_PANE_IDS.LEFT,
        });
        expect(docked.floatingWindowsBySurfaceId[APP.id]).toBeUndefined();
        expect(docked.panes.left.activeSurfaceId).toBe(APP.id);
        expect(docked.surfacesById[APP.id]).toBe(registeredApp);
    });

    it('persists floating resize bounds and can enter full screen in place', () => {
        const floating = reduce([
            {
                type: 'OPEN_SURFACE',
                surface: APP,
                paneId: DESKTOP_PANE_IDS.RIGHT,
            },
            {
                type: 'FLOAT_SURFACE',
                surfaceId: APP.id,
            },
            {
                type: 'UPDATE_FLOATING_BOUNDS',
                surfaceId: APP.id,
                bounds: { x: 120, y: 80, width: 880, height: 560 },
            },
            {
                type: 'ENTER_FULLSCREEN',
                surfaceId: APP.id,
            },
        ]);

        expect(floating.floatingWindowsBySurfaceId[APP.id]).toMatchObject({
            x: 120,
            y: 80,
            width: 880,
            height: 560,
        });
        expect(floating.fullscreenSurfaceId).toBe(APP.id);
    });
});
