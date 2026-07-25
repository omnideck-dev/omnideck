import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import useDesktopLayout, {
    DESKTOP_TAB_GROUP_IDS,
} from '../useDesktopLayout.jsx';

const CHAT = {
    id: 'destination:conversation',
    type: 'conversation',
    label: 'Chat',
};
const APP = {
    id: 'custom-app:text-lab',
    type: 'custom-app',
    label: 'Text Lab',
};

describe('useDesktopLayout', () => {
    it('presents both tabGroup stacks through the same model', () => {
        const { result } = renderHook(() => useDesktopLayout({
            initialView: CHAT,
        }));

        act(() => result.current.commands.openView(
            APP,
            DESKTOP_TAB_GROUP_IDS.RIGHT,
        ));

        expect(result.current.model.tabGroups.left.views).toEqual([CHAT]);
        expect(result.current.model.tabGroups.right.views).toEqual([APP]);
    });

    it('moves the same mounted view identity between tabGroups', () => {
        const { result } = renderHook(() => useDesktopLayout({
            initialView: CHAT,
        }));
        act(() => result.current.commands.openView(
            APP,
            DESKTOP_TAB_GROUP_IDS.RIGHT,
        ));
        const registeredApp = result.current.model.openViewsById[APP.id];

        act(() => result.current.commands.moveView(
            APP.id,
            DESKTOP_TAB_GROUP_IDS.LEFT,
        ));

        expect(result.current.model.tabGroups.right.viewIds).not.toContain(APP.id);
        expect(result.current.model.tabGroups.left.activeViewId).toBe(APP.id);
        expect(result.current.model.openViewsById[APP.id]).toBe(registeredApp);
    });

    it('allows either tabGroup to contain multiple selectable tabs', () => {
        const { result } = renderHook(() => useDesktopLayout({
            initialView: CHAT,
        }));
        act(() => {
            result.current.commands.openView(APP, DESKTOP_TAB_GROUP_IDS.LEFT);
            result.current.commands.selectView(DESKTOP_TAB_GROUP_IDS.LEFT, CHAT.id);
        });

        expect(result.current.model.tabGroups.left.viewIds).toEqual([CHAT.id, APP.id]);
        expect(result.current.model.tabGroups.left.activeViewId).toBe(CHAT.id);
    });

    it('keeps full-screen presentation out of feature data', () => {
        const { result } = renderHook(() => useDesktopLayout({
            initialView: CHAT,
        }));
        act(() => result.current.commands.setFullscreenView(CHAT.id));
        expect(result.current.model.fullscreenViewId).toBe(CHAT.id);
    });

    it('enters full screen through one activation command', () => {
        const { result } = renderHook(() => useDesktopLayout({
            initialView: CHAT,
        }));
        act(() => {
            result.current.commands.openView(APP, DESKTOP_TAB_GROUP_IDS.LEFT);
            result.current.commands.selectView(DESKTOP_TAB_GROUP_IDS.LEFT, CHAT.id);
            result.current.commands.enterFullscreen(APP.id);
        });

        expect(result.current.model.tabGroups.left.activeViewId).toBe(APP.id);
        expect(result.current.model.fullscreenViewId).toBe(APP.id);
    });

    it('starts from a validated restored layout state', () => {
        const initialLayoutState = {
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
            focusedTabGroupId: DESKTOP_TAB_GROUP_IDS.RIGHT,
            splitRatio: 64,
            fullscreenViewId: null,
        };
        const { result } = renderHook(() => useDesktopLayout({
            initialView: CHAT,
            initialLayoutState,
        }));

        expect(result.current.model.tabGroups.right.activeViewId).toBe(APP.id);
        expect(result.current.model.splitRatio).toBe(64);
    });

    it('presents floating views through the same layout model', () => {
        const { result } = renderHook(() => useDesktopLayout({
            initialView: CHAT,
        }));
        act(() => {
            result.current.commands.openView(
                APP,
                DESKTOP_TAB_GROUP_IDS.RIGHT,
            );
            result.current.commands.floatView(APP.id, {
                x: 80,
                y: 60,
                width: 640,
                height: 420,
            });
        });

        expect(result.current.model.tabGroups.right.viewIds).not.toContain(APP.id);
        expect(result.current.model.floatingByViewId[APP.id])
            .toMatchObject({
                x: 80,
                y: 60,
                width: 640,
                height: 420,
            });
        expect(result.current.model.openViewsById[APP.id]).toBe(APP);
    });
});
