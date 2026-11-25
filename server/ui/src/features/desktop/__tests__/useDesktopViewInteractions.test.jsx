import { renderHook } from '@testing-library/react';
import {
    afterEach, describe, expect, it, vi,
} from 'vitest';

import { AppEffectsProvider } from '../../app/AppEffects.jsx';


const { default: useDesktopViewInteractions } = await import(
    '../useDesktopViewInteractions.js'
);

const VIEW = { id: 'destination:conversation', label: 'Chat', closable: true };

function desktopLayout() {
    return {
        model: {
            openViewsById: { [VIEW.id]: VIEW },
            tabGroups: {
                left: { viewIds: [VIEW.id], activeViewId: VIEW.id, views: [VIEW] },
                right: { viewIds: [], activeViewId: null, views: [] },
            },
        },
        commands: {
            selectView: vi.fn(),
            closeViews: vi.fn(),
            moveView: vi.fn(),
            floatView: vi.fn(),
            enterFullscreen: vi.fn(),
        },
    };
}

const wrapper = ({ children }) => (
    <AppEffectsProvider>{children}</AppEffectsProvider>
);


describe('useDesktopViewInteractions', () => {

    it('offers the move action from getViewActions', () => {
        const { result } = renderHook(
            () => useDesktopViewInteractions({ desktopLayout: desktopLayout() }),
            { wrapper },
        );

        const actions = result.current.getViewActions(VIEW, 'left');
        expect(actions.find((action) => action.id === 'move')).toBeDefined();
    });
});
