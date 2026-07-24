import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import useDesktopWindowManager, {
    DESKTOP_PANE_IDS,
} from '../useDesktopWindowManager.jsx';

const CHAT = {
    id: 'destination:conversation',
    kind: 'conversation',
    group: 'destination',
    label: 'Chat',
};
const APP = {
    id: 'custom-app:text-lab',
    kind: 'custom-app',
    group: 'custom-app',
    label: 'Text Lab',
};

describe('useDesktopWindowManager', () => {
    it('presents both pane stacks through the same model', () => {
        const { result } = renderHook(() => useDesktopWindowManager({
            initialSurface: CHAT,
        }));

        act(() => result.current.commands.openSurface(
            APP,
            DESKTOP_PANE_IDS.RIGHT,
        ));

        expect(result.current.model.panes.left.surfaces).toEqual([CHAT]);
        expect(result.current.model.panes.right.surfaces).toEqual([APP]);
    });

    it('moves the same mounted surface identity between panes', () => {
        const { result } = renderHook(() => useDesktopWindowManager({
            initialSurface: CHAT,
        }));
        act(() => result.current.commands.openSurface(
            APP,
            DESKTOP_PANE_IDS.RIGHT,
        ));
        const registeredApp = result.current.model.surfacesById[APP.id];

        act(() => result.current.commands.moveSurface(
            APP.id,
            DESKTOP_PANE_IDS.LEFT,
        ));

        expect(result.current.model.panes.right.surfaceIds).not.toContain(APP.id);
        expect(result.current.model.panes.left.activeSurfaceId).toBe(APP.id);
        expect(result.current.model.surfacesById[APP.id]).toBe(registeredApp);
    });

    it('allows either pane to contain multiple selectable tabs', () => {
        const { result } = renderHook(() => useDesktopWindowManager({
            initialSurface: CHAT,
        }));
        act(() => {
            result.current.commands.openSurface(APP, DESKTOP_PANE_IDS.LEFT);
            result.current.commands.selectSurface(DESKTOP_PANE_IDS.LEFT, CHAT.id);
        });

        expect(result.current.model.panes.left.surfaceIds).toEqual([CHAT.id, APP.id]);
        expect(result.current.model.panes.left.activeSurfaceId).toBe(CHAT.id);
    });

    it('keeps full-screen presentation out of feature data', () => {
        const { result } = renderHook(() => useDesktopWindowManager({
            initialSurface: CHAT,
        }));
        act(() => result.current.commands.setFullscreenSurface(CHAT.id));
        expect(result.current.model.fullscreenSurfaceId).toBe(CHAT.id);
    });

    it('enters full screen through one activation command', () => {
        const { result } = renderHook(() => useDesktopWindowManager({
            initialSurface: CHAT,
        }));
        act(() => {
            result.current.commands.openSurface(APP, DESKTOP_PANE_IDS.LEFT);
            result.current.commands.selectSurface(DESKTOP_PANE_IDS.LEFT, CHAT.id);
            result.current.commands.enterFullscreen(APP.id);
        });

        expect(result.current.model.panes.left.activeSurfaceId).toBe(APP.id);
        expect(result.current.model.fullscreenSurfaceId).toBe(APP.id);
    });

    it('starts from a validated restored window state', () => {
        const initialWindowState = {
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
            focusedPaneId: DESKTOP_PANE_IDS.RIGHT,
            splitRatio: 64,
            fullscreenSurfaceId: null,
            pendingFocus: null,
        };
        const { result } = renderHook(() => useDesktopWindowManager({
            initialSurface: CHAT,
            initialWindowState,
        }));

        expect(result.current.model.panes.right.activeSurfaceId).toBe(APP.id);
        expect(result.current.model.splitRatio).toBe(64);
    });
});
